# Deploying the fork to the household host

The runbook for [REQ-002](../requirements/REQ-002.md). It takes the household host from
whatever image it is running to a named fork image, without risking the database.

This page lives here rather than in `docs/` on purpose: `docs/` is built and published to
GitHub Pages by `.github/workflows/docs.yml`, and a fork-specific runbook does not belong
in Tandoor's public documentation, where it would read as advice to strangers.

## How an image comes to exist

`.github/workflows/build-docker.yml` builds `linux/amd64,linux/arm64` and pushes on every
push to `develop`. Upstream's version of that workflow is gated
`if: github.repository_owner == 'TandoorRecipes'`, so on a fork it silently skips — the run
appears green and produces nothing. This fork removes that gate and makes the registry
follow the repository:

| Change | Why |
|---|---|
| Job-level owner gate removed | The one condition that made the workflow a no-op here |
| Docker Hub login and image name gated to the upstream owner | `github.secret_source` is `Actions` on a fork too — the fork just has no `DOCKER_*` secrets — so without this the job dies on a login with an empty username before it builds anything |
| `ghcr.io/TandoorRecipes/recipes` → `ghcr.io/${{ github.repository }}` | Resolves to the fork's own package here and to upstream's there. No fork name hardcoded, so the change stays offerable upstream |
| `type=sha,format=long` added to the tag list | Decision 5: the sha is the only identifier that cannot drift. This is what `deploy.sh` pins and what the sign-off checks |

An image is therefore addressable two ways — `:develop` (moves) and `:sha-<40 hex>` (does
not). **The deploy only ever uses the sha.**

The **frontend is built outside Docker**: the workflow runs `yarn install && yarn build` in
`vue3/`, emitting into the gitignored `cookbook/static/vue3/`, and only then does the
image's `COPY . ./` pick the assets up. An image built without that step starts cleanly and
serves no frontend at all, which is why a test asserts the ordering.

## One-time setup

1. **Confirm the ghcr package is public.** The host pulls without credentials (Decision 1).
   GitHub publishes a fork's first package as **private** by default, so after the first
   successful build open the package page → *Package settings* → *Change visibility* →
   **Public**. If it stays private the host needs a `docker login` with a read-scoped token,
   which is precisely what Decision 1 rules out.
2. **Create your target file.** It is gitignored; nothing about the household is committed.
   ```sh
   cp deploy/target.env.example deploy/target.env
   $EDITOR deploy/target.env
   ```
3. **Check ssh works non-interactively** — `ssh <your DEPLOY_SSH_HOST> true` must succeed
   without a prompt, since the deploy streams a database dump over it.

## Deploying

```sh
git push origin develop          # CI builds and publishes the image for this commit
# wait for the "Build Standard Container" run to finish
deploy/deploy.sh                 # deploys HEAD
deploy/deploy.sh <commit-sha>    # deploys (or rolls back to) a specific published commit
```

What it does, in this order, stopping at the first failure:

1. **Reads `deploy/target.env`** and refuses to run without it. Nothing that identifies a
   machine is defaulted — a defaulted host is how a deploy reaches the wrong box. It then
   pre-checks that the image's manifest actually carries a `linux/arm64` entry, so an
   amd64-only build is caught *before* the database is touched.
2. **Takes the backup and proves it** (Decision 4 — the gate this whole REQ is built
   around). `pg_dump -Fc` runs in the host's database container and is **streamed to the
   workstation**; the host's root filesystem is at 88 % and must not hold a copy of its own
   database. A sha256 is computed on the host *in flight*, over the very bytes leaving
   `pg_dump`, and `verify_dump.sh` checks the arrived file against it. **If verification
   fails the deploy stops here and nothing has changed.**
3. **Points the stack at the fork image** by writing a marker-tagged
   `docker-compose.override.yml` next to the host's compose file, then `pull` + `up -d`.
   The household's own `docker-compose.yml` is never edited. If an override is already
   there and was not written by this script, the deploy stops rather than clobber it.
4. **Settles migrations.** `boot.sh` migrates on container start, so the script *waits* for
   that run to finish and then reports the applied migrations; it only issues a `migrate`
   itself if something is still unapplied (a host that does not migrate on boot). Either way
   the log carries a visible migration step *after* the verified backup.

   It used to issue an unconditional `migrate` here, on the assumption that boot.sh's run
   made it a no-op. The first deploy that actually carried a migration (REQ-003) disproved
   that: both sessions reached the same `ALTER TABLE ... ADD COLUMN`, the explicit one
   blocked on the lock and then died with `DuplicateColumn`, and the deploy aborted at step
   4 — with the image, the schema and the site all perfectly fine. A deploy that reports
   failure over a success is worse than one that fails honestly.
5. **Reports the version** now running — the baked-in `TANDOOR_VERSION` / `TANDOOR_REF` plus
   the image id and repo digest.

## What "verified restorable" does and does not mean

`verify_dump.sh` is deliberately serverless — no PostgreSQL instance is contacted, which is
what makes it testable without a host and cheap enough to run on every deploy.

| Check | Catches |
|---|---|
| sha256 against the digest computed at the source | Any damage in transit — a dropped ssh connection, a truncated stream, a flipped byte |
| `pg_restore --list` | A plain-SQL dump handed over by mistake, a non-archive, a damaged header, an archive that would restore nothing |
| `pg_restore -f /dev/null` | Truncation, and corruption of any compressed data block |

**The honest limit.** `pg_restore` alone does *not* catch every byte flip: a custom-format
archive stores TOC entries as length-prefixed plain SQL that `pg_restore` emits verbatim
without validating, so damage inside a `CREATE TABLE` statement passes both `pg_restore`
checks. This was verified empirically while writing the script, not assumed — which is why
the sha256 check exists and why `deploy.sh` always supplies a digest.

**Also not proven:** that the dump would apply cleanly into a live cluster. Proving *that*
needs a server and a second copy of the database — a real restore on a host with ~1 GB free
RAM and a nearly full disk, next to the household's DNS and password manager. That trade-off
was reviewed and accepted; see fork B in
[the plan](../requirements/plans/0002-fork-image-delivery.md).

## Evidence (for `steward validate REQ-002`)

AC3 and AC4 are graded by the System-Test phase, in a fresh session that never sees the
implementation diff. It captures the files below into `$DEVSTEWARD_EVIDENCE_DIR`; the engine
then runs the two grading tests in `cookbook/tests/other/test_fork_delivery.py` against
them. Outside a validation those tests skip; with an evidence dir set, a missing file is a
hard failure, so neither can pass by finding nothing.

| File | How to produce it |
|---|---|
| `deploy.log` | the full console output of the deploy run: `deploy/deploy.sh 2>&1 \| tee "$DEVSTEWARD_EVIDENCE_DIR/deploy.log"` |
| `manifest-inspect.json` | `docker manifest inspect ghcr.io/dr-froehlich/recipes:sha-<sha> > "$DEVSTEWARD_EVIDENCE_DIR/manifest-inspect.json"` |
| `index-digest.txt` | `docker buildx imagetools inspect --format '{{.Manifest.Digest}}' ghcr.io/dr-froehlich/recipes:sha-<sha>` |
| `running-image-digest.txt` | on the host, from the **image**, not the container (see below) |
| `signoff.json` | the human observation, recorded as three booleans (below) |

```sh
# running-image-digest.txt — a container has no .RepoDigests; resolve to its image first
cd <compose-dir>
cid=$(docker compose ps -q web_recipes)
img=$(docker inspect --format '{{.Image}}' "$cid")
docker image inspect --format '{{join .RepoDigests "\n"}}' "$img"
```

`index-digest.txt` looks redundant next to `manifest-inspect.json` and is not. Pulling a
multi-arch **tag** records the digest of the *index* in the host's `RepoDigests`, whereas
`docker manifest inspect` prints only the child manifests — never the index's own digest. So
comparing the host's digest against the child digests alone fails on a perfectly good
deploy. Both this and the container-vs-image mistake above were found by running the real
deploy and grading the real evidence, not by reasoning about it.

```json
{
  "system_page_shows_fork_commit": true,
  "recipes_and_images_render": true,
  "backup_verified_before_migration": true
}
```

Those are AC4's three PASS conditions, observed at `<public-url>/system/` signed in as a
superuser and on the recipe list page. Any one of them false or absent is a FAIL. The
third is additionally cross-checked against `deploy.log` independently of the sign-off:
the test asserts that `Backup gate passed` appears *before* `Step 4/5`, so a deploy that
migrated ahead of a verified backup cannot be signed off as if it had not.

## Rolling back

Deploy an earlier published sha — the same script, no remembered command line:

```sh
deploy/deploy.sh <previous-sha>
```

To leave the fork entirely and return to the image the host's own compose file names, delete
the override and bring the stack back up:

```sh
ssh <host> 'cd <compose-dir> && rm docker-compose.override.yml && docker compose up -d'
```

A rollback of the *image* is not a rollback of the *database*. If a migration has run, going
back to an older image can leave the schema ahead of the code. The dump from step 2 of that
deploy is the restore point; it is in `deploy/dumps/`.

## Not covered here

Both are named rather than silently omitted:

- **Pulling in future upstream releases** — the rebase-onto-upstream-`develop` workflow.
  Decision 6 defers it to a follow-on REQ, to be intaken when upstream ships a release worth
  taking.
- **A standing backup regime.** Decision 4 gates *the deploy*. It is not a schedule, and the
  dumps in `deploy/dumps/` are a by-product of deploying, not a backup strategy.
