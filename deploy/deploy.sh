#!/usr/bin/env bash
#
# deploy.sh — take the household host from whatever it is running to a named fork image.
#
# Run from the workstation, not on the host. REQ-002's Deploy section, in its five steps:
#
#   1. read the target from the gitignored deploy/target.env, refusing to run without it
#   2. dump the live database and prove the dump is restorable — stop if it is not
#   3. point the compose stack at the fork image by sha and bring it up
#   4. run migrations
#   5. report the version the host is now running
#
# Nothing about the household — host, path, IP, domain — is committed. It all lives in
# target.env (see target.env.example), which .gitignore excludes. See README.md.
#
# usage: deploy.sh [<commit-sha>] [--yes]
#
#   <commit-sha>  the 40-character commit to deploy. Defaults to HEAD. Passing an earlier
#                 sha is the rollback path: same script, no remembered command line.
#   --yes         skip the confirmation prompt (for a re-run you have already reviewed).

set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/.." && pwd)

die() {
    echo "" >&2
    echo "DEPLOY ABORTED: $*" >&2
    exit 1
}

step() {
    echo ""
    echo "=============================================================================="
    echo "  $*"
    echo "=============================================================================="
}

sha=""
assume_yes=0

while [ $# -gt 0 ]; do
    case "$1" in
        --yes | -y)
            assume_yes=1
            shift
            ;;
        -h | --help)
            sed -n '3,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        -*)
            die "unknown option: $1"
            ;;
        *)
            [ -z "$sha" ] || die "more than one commit sha given"
            sha=$1
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------------------
# Step 1 — target configuration. An absent file is a hard stop, and nothing that identifies
# a machine is defaulted: a defaulted host is how a deploy reaches the wrong box.
# ---------------------------------------------------------------------------------------
step "Step 1/5  Target configuration"

target_env="$here/target.env"
[ -f "$target_env" ] || die "$target_env is missing.
    This file names the household host and is deliberately not committed.
    Copy deploy/target.env.example to deploy/target.env and fill it in."

# shellcheck source=/dev/null
set -a
. "$target_env"
set +a

for key in DEPLOY_SSH_HOST DEPLOY_COMPOSE_DIR DEPLOY_PUBLIC_URL; do
    [ -n "${!key:-}" ] || die "$key is not set in $target_env"
done

DEPLOY_IMAGE=${DEPLOY_IMAGE:-ghcr.io/dr-froehlich/recipes}
DEPLOY_DB_SERVICE=${DEPLOY_DB_SERVICE:-db_recipes}
DEPLOY_APP_SERVICE=${DEPLOY_APP_SERVICE:-web_recipes}
DEPLOY_DUMP_DIR=${DEPLOY_DUMP_DIR:-$here/dumps}

if [ -z "$sha" ]; then
    sha=$(git -C "$repo" rev-parse HEAD)
    echo "No sha given; using HEAD."
fi

case "$sha" in
    *[!0-9a-fA-F]* | "") die "not a commit sha: $sha" ;;
esac
[ ${#sha} -eq 40 ] || die "need the full 40-character sha, got ${#sha} characters: $sha
    (try: git rev-parse $sha)"
sha=$(printf '%s' "$sha" | tr 'A-F' 'a-f')

image_ref="$DEPLOY_IMAGE:sha-$sha"

# Warn — but do not stop — when the sha is not on the fork's develop. A deliberate rollback
# to an older published sha is legitimate; deploying something never pushed is not.
if git -C "$repo" rev-parse --verify --quiet "$sha^{commit}" >/dev/null 2>&1; then
    if ! git -C "$repo" merge-base --is-ancestor "$sha" origin/develop 2>/dev/null; then
        echo "WARNING: $sha is not an ancestor of origin/develop."
        echo "         If it was never pushed, CI never built an image for it."
    fi
else
    echo "WARNING: $sha is not a commit in this clone; cannot check that it was pushed."
fi

echo "  host          $DEPLOY_SSH_HOST"
echo "  compose dir   $DEPLOY_COMPOSE_DIR"
echo "  image         $image_ref"
echo "  public url    $DEPLOY_PUBLIC_URL"

# Every remote command runs under `bash -c` with the compose directory as cwd, so the
# host's login shell (which may be sh or zsh) never has to support what we send it.
remote() {
    ssh "$DEPLOY_SSH_HOST" "bash -c $(printf '%q' "cd $DEPLOY_COMPOSE_DIR && $1")"
}

ssh "$DEPLOY_SSH_HOST" true 2>/dev/null || die "cannot ssh to $DEPLOY_SSH_HOST"
remote "test -f docker-compose.yml" ||
    die "no docker-compose.yml in $DEPLOY_COMPOSE_DIR on $DEPLOY_SSH_HOST"

# Refuse an image the host cannot run. Catches an amd64-only build — the exact failure this
# REQ exists to prevent — before the database is touched.
if command -v docker >/dev/null 2>&1; then
    if manifest=$(docker manifest inspect "$image_ref" 2>&1); then
        printf '%s' "$manifest" | grep -q '"architecture": *"arm64"' ||
            die "$image_ref has no linux/arm64 entry in its manifest; the host cannot run it."
        echo "  manifest      linux/arm64 present"
    else
        die "cannot read the manifest for $image_ref: ${manifest//$'\n'/ }
    Has CI finished building this sha? Is the ghcr package public?"
    fi
else
    echo "WARNING: docker is not on PATH here; skipping the arm64 manifest pre-check."
fi

if [ "$assume_yes" -eq 0 ]; then
    echo ""
    printf 'Deploy this image to the household host? [y/N] '
    read -r reply
    case "$reply" in
        y | Y | yes | YES) ;;
        *) die "cancelled at the confirmation prompt (nothing was changed)" ;;
    esac
fi

# ---------------------------------------------------------------------------------------
# Step 2 — the backup gate (Decision 4).
#
# The dump is streamed to the workstation: the host's root filesystem is at 88 % and must
# not carry a copy of its own database.
#
# The digest is computed ON THE HOST, in flight, over the very bytes leaving pg_dump —
# `tee` feeds sha256sum while the same stream continues to our stdout. Hashing a *second*
# pg_dump run would be worthless: two runs differ in their header timestamp and in any row
# written between them, so the digests would never match. One stream, hashed at its source,
# is what lets verify_dump.sh tell "arrived intact" from "arrived damaged".
# ---------------------------------------------------------------------------------------
step "Step 2/5  Database dump and restore verification"

mkdir -p "$DEPLOY_DUMP_DIR"
chmod 700 "$DEPLOY_DUMP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dump="$DEPLOY_DUMP_DIR/tandoor-$stamp.dump"
dump_err="$dump.stderr"

# POSTGRES_USER/POSTGRES_DB are resolved inside the db container from its own environment,
# so no database credential is needed here or in target.env.
dump_cmd="set -o pipefail; docker compose exec -T $DEPLOY_DB_SERVICE sh -c 'pg_dump -Fc -U \"\$POSTGRES_USER\" \"\$POSTGRES_DB\"' | tee >(sha256sum | cut -d' ' -f1 | sed 's/^/SHA256:/' >&2)"

echo "Dumping $DEPLOY_DB_SERVICE on $DEPLOY_SSH_HOST -> $dump"
if ! remote "$dump_cmd" >"$dump" 2>"$dump_err"; then
    echo "--- remote stderr ---" >&2
    cat "$dump_err" >&2 || true
    rm -f "$dump" "$dump_err"
    die "pg_dump failed on the host. Nothing was changed."
fi

source_sha=$(grep -m1 '^SHA256:' "$dump_err" | cut -d: -f2 || true)
# Anything the host said that was not our digest line is real pg_dump output worth seeing.
if grep -qv '^SHA256:' "$dump_err" 2>/dev/null; then
    echo "--- remote stderr ---"
    grep -v '^SHA256:' "$dump_err" || true
fi
rm -f "$dump_err"

[ -n "$source_sha" ] || die "the host did not report a source digest for the dump.
    Refusing to continue: an unverified dump is not a restore point."

echo "Verifying the dump"
if ! "$here/verify_dump.sh" --expect-sha256 "$source_sha" "$dump"; then
    die "the dump is not restorable. The database was NOT touched and no migration ran.
    The unusable dump has been kept for inspection at: $dump"
fi
echo "Backup gate passed. Migrations may proceed."

# ---------------------------------------------------------------------------------------
# Step 3 — point the stack at the fork image and bring it up.
#
# Done with a compose override rather than by editing the household's docker-compose.yml,
# so this script never rewrites a file it did not author. The override carries a marker
# line; if a foreign override is already there, we stop rather than clobber it.
# ---------------------------------------------------------------------------------------
step "Step 3/5  Point the stack at $image_ref"

marker="# managed by tandoor fork deploy.sh - delete to return to the base compose file"

if remote "test -f docker-compose.override.yml"; then
    remote "head -1 docker-compose.override.yml | grep -qF '$marker'" ||
        die "docker-compose.override.yml exists on the host and was not written by this
    script. Refusing to overwrite it. Move it aside, or fold the image override in by hand."
fi

previous_image=$(remote "docker compose ps -q $DEPLOY_APP_SERVICE 2>/dev/null | head -1 | xargs -r docker inspect --format '{{.Config.Image}}'" || true)
echo "  currently running: ${previous_image:-<nothing>}"

override_body="$marker
services:
  $DEPLOY_APP_SERVICE:
    image: $image_ref"

remote "cat > docker-compose.override.yml" <<<"$override_body"
echo "  wrote $DEPLOY_COMPOSE_DIR/docker-compose.override.yml"

remote "docker compose pull $DEPLOY_APP_SERVICE"
remote "docker compose up -d"

# ---------------------------------------------------------------------------------------
# Step 4 — migrations. boot.sh already runs `manage.py migrate` when the container starts,
# so this is normally a no-op; it is run explicitly anyway so the deploy log carries a
# visible, ordered migration step after the verified backup (AC4 reads this log).
# ---------------------------------------------------------------------------------------
step "Step 4/5  Migrations"

echo "Waiting for $DEPLOY_APP_SERVICE to accept commands"
for attempt in $(seq 1 30); do
    if remote "docker compose exec -T $DEPLOY_APP_SERVICE test -f /opt/recipes/manage.py" 2>/dev/null; then
        break
    fi
    [ "$attempt" -lt 30 ] || die "$DEPLOY_APP_SERVICE did not come up.
    The verified database dump is intact at $dump.
    The previously running image was: ${previous_image:-unknown}"
    sleep 2
done

remote "docker compose exec -T $DEPLOY_APP_SERVICE /opt/recipes/venv/bin/python manage.py migrate --noinput"

# ---------------------------------------------------------------------------------------
# Step 5 — report what the host is now running.
# ---------------------------------------------------------------------------------------
step "Step 5/5  Deployed version"

echo "--- baked-in version (cookbook/version_info.py, written by version.py at image build) ---"
remote "docker compose exec -T $DEPLOY_APP_SERVICE grep -E '^TANDOOR_(VERSION|REF)' cookbook/version_info.py" || true

echo ""
echo "--- running image ---"
container=$(remote "docker compose ps -q $DEPLOY_APP_SERVICE | head -1")
image_id=$(remote "docker inspect --format '{{.Image}}' $container" || true)
repo_digests=$(remote "docker image inspect --format '{{join .RepoDigests \" \"}}' $image_ref" || true)
echo "  image ref     $image_ref"
echo "  image id      ${image_id:-<unknown>}"
echo "  repo digest   ${repo_digests:-<unknown>}"

echo ""
echo "=============================================================================="
echo "  Deploy complete."
echo ""
echo "  Commit:  $sha"
echo "  Image:   $image_ref"
echo "  Backup:  $dump (verified restorable before any migration)"
echo "  Verify:  $DEPLOY_PUBLIC_URL/system/  (signed in as a superuser)"
echo ""
echo "  The system page version block should name the commit above and the develop"
echo "  branch. An upstream release tag there means the deploy did not take."
echo "=============================================================================="
