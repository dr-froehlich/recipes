#!/usr/bin/env bash
#
# verify_dump.sh — the backup gate for the fork deploy.
#
# REQ-002 Decision 4: no migration runs behind an unverified backup. A dump that was never
# checked is not a restore point, so this script decides whether a PostgreSQL custom-format
# archive is actually usable. deploy.sh calls it before it changes anything on the host; a
# non-zero exit stops the deploy.
#
# It is a separate script on purpose: a verifier reachable only by running a full deploy
# could not be tested without a production host, and would have to be asserted rather than
# observed. AC2 drives this file directly against synthetic archives.
#
# WHAT IS CHECKED, AND WHAT EACH CHECK IS WORTH
#
#   1. --expect-sha256 (optional, supplied by deploy.sh)
#        The digest computed on the household host over exactly the bytes pg_dump wrote,
#        compared against the file that arrived here. This is the check that covers the
#        transfer, which is where damage realistically happens: the dump is streamed over
#        ssh, and a dropped connection or a mangled byte in flight is caught here and
#        nowhere else.
#
#   2. pg_restore --list
#        The archive header and table of contents parse, and the TOC is non-empty. Catches
#        a plain-SQL dump handed over by mistake, a file that is not an archive, a header
#        damaged in the first bytes, and an archive that would restore nothing.
#
#   3. pg_restore -f /dev/null
#        Walks the entire archive, decompressing and emitting every data block as SQL.
#        Catches truncation and damage to compressed data blocks (zlib checks each block).
#
# The honest limit: checks 2 and 3 do NOT catch every possible byte flip. A custom-format
# archive stores TOC entries as length-prefixed plain SQL text, which pg_restore emits
# verbatim without validating; flipping bytes inside a CREATE TABLE statement produces
# corrupt-but-well-formed output and passes both checks. This was verified empirically
# while writing the script, not assumed. Check 1 is what closes that gap, which is why
# deploy.sh always passes a digest and only a manual invocation may omit it.
#
# Not proven by any of this: that the SQL would apply cleanly into a live cluster. Proving
# that needs a server and a second copy of the database, which the household host (root
# filesystem at 88 %, ~1 GB free RAM) cannot afford. That trade-off was reviewed and
# accepted; see requirements/plans/0002-fork-image-delivery.md, fork B.
#
# Exit codes:
#   0  the dump is usable
#   1  the dump is NOT usable — stop
#   2  the check could not be performed (bad usage, missing tool) — also stop

set -euo pipefail

usage() {
    cat >&2 <<'EOF'
usage: verify_dump.sh [--expect-sha256 <hex>] <dump-file>

Verifies that a PostgreSQL custom-format (pg_dump -Fc) archive is usable.

  --expect-sha256 <hex>  digest computed at the source; verifies the file arrived intact.
                         deploy.sh always supplies this. Omitting it skips the only check
                         that catches arbitrary byte corruption.

Exits 0 if usable, 1 if not, 2 if the check could not be performed.
EOF
}

# A failure of the dump itself: the deploy must stop, and the reason is about the backup.
unusable() {
    echo "UNRESTORABLE: $*" >&2
    exit 1
}

# A failure of the checking apparatus. Also stops the deploy — an unperformed check is not
# a pass — but says so differently, because the fix is different.
cannot_check() {
    echo "CANNOT VERIFY: $*" >&2
    exit 2
}

expected_sha=""

while [ $# -gt 0 ]; do
    case "$1" in
        --expect-sha256)
            [ $# -ge 2 ] || { usage; exit 2; }
            expected_sha=$2
            shift 2
            ;;
        -h | --help)
            usage
            exit 2
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "unknown option: $1" >&2
            usage
            exit 2
            ;;
        *)
            break
            ;;
    esac
done

[ $# -eq 1 ] || { usage; exit 2; }

dump=$1

command -v pg_restore >/dev/null 2>&1 || cannot_check "pg_restore is not on PATH"

[ -e "$dump" ] || unusable "no such file: $dump"
[ -f "$dump" ] || unusable "not a regular file: $dump"
[ -r "$dump" ] || cannot_check "file is not readable: $dump"
[ -s "$dump" ] || unusable "file is empty: $dump"

size=$(wc -c <"$dump" | tr -d '[:space:]')

# 1. Did the bytes arrive exactly as they left the host?
if [ -n "$expected_sha" ]; then
    command -v sha256sum >/dev/null 2>&1 || cannot_check "sha256sum is not on PATH"
    actual_sha=$(sha256sum "$dump" | cut -d' ' -f1)
    # Normalise case so a hand-pasted uppercase digest does not read as corruption.
    if [ "$(printf '%s' "$actual_sha" | tr 'A-F' 'a-f')" != "$(printf '%s' "$expected_sha" | tr 'A-F' 'a-f')" ]; then
        unusable "sha256 mismatch — the dump did not arrive intact. expected $expected_sha, got $actual_sha"
    fi
fi

# 2. Header and table of contents parse, and there is something in there to restore.
if ! toc=$(pg_restore --list "$dump" 2>&1); then
    unusable "pg_restore --list failed on $dump ($size bytes): ${toc//$'\n'/ }"
fi

# Count real TOC entries, ignoring the ';'-prefixed comment banner pg_restore always emits.
# A zero-entry archive parses fine and restores nothing, which is not a restore point.
entries=$(printf '%s\n' "$toc" | grep -c -v -e '^;' -e '^[[:space:]]*$' || true)
[ "$entries" -gt 0 ] || unusable "archive contains no restorable entries: $dump"

# 3. Full read-through: decompress and emit every data block.
if ! err=$(pg_restore -f /dev/null "$dump" 2>&1); then
    unusable "pg_restore could not read the archive through to the end: ${err//$'\n'/ }"
fi

# pg_restore can succeed while still reporting trouble on stderr; treat that as a failure
# rather than letting a warning-shaped corruption slip past the gate.
if [ -n "$err" ]; then
    unusable "pg_restore reported errors while reading the archive: ${err//$'\n'/ }"
fi

if [ -n "$expected_sha" ]; then
    echo "RESTORABLE: $dump ($size bytes, $entries archive entries, sha256 verified)"
else
    echo "RESTORABLE: $dump ($size bytes, $entries archive entries, NO source digest supplied)"
fi
