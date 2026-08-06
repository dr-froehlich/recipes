"""Acceptance tests for REQ-002 — fork image delivery.

AC1 and AC2 are `regression`: they read the committed workflow and drive the committed
dump verifier, so they run anywhere the repo is checked out (AC2 needs only the
``pg_restore`` binary, no PostgreSQL server).

AC3 and AC4 are `artifact` and `manual`. They are graded by the System-Test phase against
evidence captured by a session that has network access to ghcr.io and ssh access to the
household host, and skip in an ordinary full-suite run where neither is available. Once the
engine sets DEVSTEWARD_EVIDENCE_DIR — the only context in which they are named as acceptance
criteria — missing evidence is a hard failure, so neither can pass by finding nothing.
See deploy/README.md § Evidence for the exact files and how to produce them.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / '.github/workflows/build-docker.yml'
VERIFY_DUMP = REPO_ROOT / 'deploy/verify_dump.sh'
FIXTURE_DUMP = Path(__file__).parent / 'test_data/fork_delivery/restorable.dump'

# The fork this repository publishes to. REQ-002 Decision 1.
FORK_REPOSITORY = 'dr-froehlich/recipes'
FORK_IMAGE = f'ghcr.io/{FORK_REPOSITORY}'
UPSTREAM_OWNER = 'TandoorRecipes'


def _resolve_image_expression(entry, repository):
    """Resolve the subset of GitHub Actions expression syntax the images list uses.

    The workflow names the fork's registry as ``ghcr.io/${{ github.repository }}`` rather
    than hardcoding a fork name, so that the diff stays offerable upstream (plan 0002,
    fork A). Asserting on the literal text would therefore prove nothing about where the
    image actually lands — the test has to *evaluate* the expression the way Actions does.

    Returns the resolved image name, or '' for an entry that resolves to nothing.
    """
    owner = repository.split('/')[0]
    entry = entry.strip()
    if not entry:
        return ''

    # `${{ <cond> && 'a' || 'b' }}` — the ternary upstream's Docker Hub entry now uses.
    ternary = re.fullmatch(
        r"\$\{\{\s*github\.repository_owner\s*==\s*'([^']*)'\s*&&\s*'([^']*)'\s*\|\|\s*'([^']*)'\s*\}\}",
        entry,
    )
    if ternary:
        wanted, when_true, when_false = ternary.groups()
        return when_true if owner == wanted else when_false

    resolved = entry.replace('${{ github.repository }}', repository)
    resolved = resolved.replace('${{ github.repository_owner }}', owner)
    if '${{' in resolved:
        pytest.fail(f'images entry uses expression syntax this test cannot resolve: {entry!r}')
    return resolved


def _images_for(meta_step, repository):
    raw = meta_step['with']['images']
    return [img for img in (_resolve_image_expression(line, repository) for line in raw.splitlines()) if img]


def _step_index(steps, predicate):
    for i, s in enumerate(steps):
        if predicate(s):
            return i
    return -1


# ------------------------------------------------------------------------------------
# AC1 — the build workflow is fork-enabled
# ------------------------------------------------------------------------------------
def test_build_workflow_is_fork_enabled():
    """The Docker build workflow actually produces a fork image for this repository.

    Upstream gates the build job on ``github.repository_owner == 'TandoorRecipes'``, so on
    a fork it silently skips: the run reports success and publishes nothing. Each assertion
    below is one way that silence can come back.
    """
    assert WORKFLOW.is_file(), f'{WORKFLOW} is missing'
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))

    job = workflow['jobs']['build-container']

    # 1. No job-level condition may restrict the build to the upstream owner.
    job_if = str(job.get('if', ''))
    assert UPSTREAM_OWNER not in job_if, (f'build-container is still gated on the upstream owner (if: {job_if!r}); '
                                          'on this fork the job would skip and publish nothing')

    # 2. The host is aarch64 — an image without linux/arm64 cannot run there at all.
    platforms = [p.strip() for p in str(job['strategy']['matrix']['include'][0]['platforms']).split(',')]
    assert 'linux/arm64' in platforms, f'linux/arm64 missing from the platform list: {platforms}'

    steps = job['steps']

    # 3. The published image list must include the fork's ghcr image once resolved.
    meta_idx = _step_index(steps, lambda s: str(s.get('uses', '')).startswith('docker/metadata-action'))
    assert meta_idx >= 0, 'no docker/metadata-action step found'
    images = _images_for(steps[meta_idx], FORK_REPOSITORY)
    assert FORK_IMAGE in images, f'{FORK_IMAGE} not among the published images {images}'

    # ...and on upstream the same workflow must still publish upstream's images, so the
    # diff stays something that could be offered back rather than a fork-only hack.
    upstream_images = _images_for(steps[meta_idx], f'{UPSTREAM_OWNER}/recipes')
    assert f'ghcr.io/{UPSTREAM_OWNER}/recipes' in upstream_images, (f'the workflow no longer publishes upstream ghcr image on upstream: {upstream_images}')

    # 4. Images must be addressable by commit sha (Decision 5) — a moving branch tag is a
    #    convenience, the sha is what the deploy pins and the sign-off checks.
    tags = str(steps[meta_idx]['with']['tags'])
    assert 'type=sha' in tags, f'no sha tag configured; the deploy has nothing stable to pin:\n{tags}'
    assert 'format=long' in tags, f'sha tag is not the full 40-character form:\n{tags}'

    # 5. The SPA is built OUTSIDE Docker into the gitignored cookbook/static/vue3/, and the
    #    image's `COPY . ./` picks it up. Build the image first and it starts cleanly while
    #    serving no frontend at all — a failure that is invisible until a browser hits it.
    yarn_idx = _step_index(
        steps,
        lambda s: s.get('working-directory') == './vue3' and 'yarn build' in str(s.get('run', '')),
    )
    assert yarn_idx >= 0, 'no `yarn build` step in ./vue3 — the image would ship without a frontend'

    build_idx = _step_index(steps, lambda s: str(s.get('uses', '')).startswith('docker/build-push-action'))
    assert build_idx >= 0, 'no docker/build-push-action step found'
    assert yarn_idx < build_idx, (
        f'the vue3 build (step {yarn_idx}) must run before the image build (step {build_idx}); '
        'otherwise the SPA assets do not exist in the build context'
    )


# ------------------------------------------------------------------------------------
# AC2 — the deploy pre-flight refuses to continue behind an unusable backup
# ------------------------------------------------------------------------------------
def _verify(dump_path, expect_sha=None):
    cmd = [str(VERIFY_DUMP)]
    if expect_sha is not None:
        cmd += ['--expect-sha256', expect_sha]
    cmd.append(str(dump_path))
    return subprocess.run(cmd, capture_output=True, text=True)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_dump_verification_rejects_unrestorable_dump(tmp_path):
    """A migration can never run behind a dump nobody checked (REQ-002 Decision 4).

    Drives the committed verifier as a subprocess, exactly as deploy.sh does. The
    well-formed case uses a committed custom-format archive generated once from an empty
    scratch database, so the test needs no PostgreSQL server — only the ``pg_restore``
    binary, which REQ-002's Notes already require.
    """
    assert VERIFY_DUMP.is_file(), f'{VERIFY_DUMP} is missing'
    assert os.access(VERIFY_DUMP, os.X_OK), f'{VERIFY_DUMP} is not executable'
    assert FIXTURE_DUMP.is_file(), f'{FIXTURE_DUMP} is missing'
    assert shutil.which('pg_restore'), 'pg_restore is not on PATH (see REQ-002 Notes)'

    good_sha = _sha256(FIXTURE_DUMP)

    # A well-formed archive passes — otherwise the gate would just block every deploy,
    # which is not the same thing as being safe.
    ok = _verify(FIXTURE_DUMP, good_sha)
    assert ok.returncode == 0, f'a well-formed dump was rejected:\n{ok.stdout}\n{ok.stderr}'
    assert 'RESTORABLE' in ok.stdout
    assert 'sha256 verified' in ok.stdout

    # Truncated — the stream died partway through.
    truncated = tmp_path / 'truncated.dump'
    truncated.write_bytes(FIXTURE_DUMP.read_bytes()[:800])
    res = _verify(truncated)
    assert res.returncode == 1, f'a truncated dump was accepted:\n{res.stdout}\n{res.stderr}'
    assert 'UNRESTORABLE' in res.stderr

    # Corrupt in the header region — not an archive pg_restore can even open.
    corrupt = tmp_path / 'corrupt.dump'
    data = bytearray(FIXTURE_DUMP.read_bytes())
    data[10:40] = b'\xde\xad\xbe\xef' * 7 + b'\xde\xad'
    corrupt.write_bytes(bytes(data))
    res = _verify(corrupt)
    assert res.returncode == 1, f'a corrupt dump was accepted:\n{res.stdout}\n{res.stderr}'
    assert 'UNRESTORABLE' in res.stderr

    # Empty file — pg_dump produced nothing at all.
    empty = tmp_path / 'empty.dump'
    empty.write_bytes(b'')
    res = _verify(empty)
    assert res.returncode == 1, f'an empty dump was accepted:\n{res.stdout}\n{res.stderr}'

    # Missing file — the dump step never ran.
    res = _verify(tmp_path / 'absent.dump')
    assert res.returncode == 1, f'a missing dump was accepted:\n{res.stdout}\n{res.stderr}'

    # A plain-SQL dump handed over where a custom-format archive was required.
    plain = tmp_path / 'plain.sql'
    plain.write_text('-- PostgreSQL database dump\nCREATE TABLE t (id integer);\n')
    res = _verify(plain)
    assert res.returncode == 1, f'a plain-SQL dump was accepted:\n{res.stdout}\n{res.stderr}'

    # Intact archive, wrong source digest: the bytes changed between the host and here.
    # pg_restore alone cannot see this — a custom-format archive stores TOC entries as
    # plain SQL text it emits without validating — which is why the digest check exists.
    res = _verify(FIXTURE_DUMP, '0' * 64)
    assert res.returncode == 1, f'a dump that did not match its source digest was accepted:\n{res.stdout}'
    assert 'sha256 mismatch' in res.stderr


# ------------------------------------------------------------------------------------
# AC3 / AC4 — graded by the System-Test phase against captured evidence
# ------------------------------------------------------------------------------------
def _evidence_dir():
    """The evidence directory the System Tester captured into, or None when not validating."""
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    return Path(raw) if raw else None


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation.

    The engine sets DEVSTEWARD_EVIDENCE_DIR when it runs an `artifact` criterion's test, so
    its absence means this is an ordinary full-suite run on a workstation with no ghcr
    access and no ssh to the household host. Skipping there is deliberate and is the only
    correct behaviour: these two criteria are graded by `steward validate REQ-002`, and a
    hard failure would redden every unrelated land gate in the project.

    The skip cannot launder a pass. Once the evidence dir *is* set — the only context in
    which these tests are named as acceptance criteria — a missing artifact is an assertion
    failure, never a skip, so neither test can be satisfied by finding nothing.
    """
    evidence = _evidence_dir()
    if evidence is None:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-002)')
    path = evidence / name
    assert path.is_file(), f'required evidence {name} was not captured into {evidence}'
    return path


def _has_linux_arm64(node):
    """True if any platform block anywhere in the manifest JSON is linux/arm64."""
    if isinstance(node, dict):
        platform = node.get('platform')
        if isinstance(platform, dict) and platform.get('architecture') == 'arm64' and platform.get('os') == 'linux':
            return True
        return any(_has_linux_arm64(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_linux_arm64(v) for v in node)
    return False


def _collect_manifest_digests(node, under_layers=False):
    """Every manifest-level digest in the JSON, ignoring layer and config digests.

    `docker manifest inspect`, `docker manifest inspect --verbose` and
    `docker buildx imagetools inspect --raw` all spell this differently, and which digest
    the host reports depends on how the image was pulled: pulling a multi-arch tag records
    the *index* digest in RepoDigests, not the per-platform manifest digest. So rather than
    insisting on one capture shape, collect every digest that could legitimately identify
    the image and let the caller check membership.
    """
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            skip = under_layers or key in ('layers', 'config', 'fsLayers', 'history')
            if key == 'digest' and isinstance(value, str) and not skip:
                found.add(value)
            else:
                found |= _collect_manifest_digests(value, under_layers=skip)
    elif isinstance(node, list):
        for item in node:
            found |= _collect_manifest_digests(item, under_layers=under_layers)
    return found


def test_published_manifest_matches_running_image():
    """AC3 — the published arm64 image is the image the host is actually running.

    Evidence the System Tester must capture (see deploy/README.md § Evidence):

      manifest-inspect.json     `docker manifest inspect <image>:sha-<sha>`
      index-digest.txt          `docker buildx imagetools inspect --format '{{.Manifest.Digest}}'`
      running-image-digest.txt  the host's RepoDigest for the running app container

    index-digest.txt is not redundant. Pulling a multi-arch tag records the digest of the
    *index* in the host's RepoDigests, while `docker manifest inspect` prints only the child
    manifests — never the index's own digest. Comparing the host's digest against the child
    digests alone therefore fails on a perfectly good deploy. Found by running the real
    deploy against the household host, not by reasoning about it.
    """
    manifest = json.loads(_require_evidence('manifest-inspect.json').read_text(encoding='utf-8'))

    assert _has_linux_arm64(manifest), (f'no linux/arm64 entry in the published manifest — the aarch64 host cannot run it: {manifest}')

    running = _require_evidence('running-image-digest.txt').read_text(encoding='utf-8').strip()
    assert running, 'the captured running-image digest is empty'
    assert 'sha256:' in running, f'running-image-digest.txt does not contain a digest: {running!r}'

    index_digest = _require_evidence('index-digest.txt').read_text(encoding='utf-8').strip()
    assert index_digest.startswith('sha256:'), f'index-digest.txt is not a digest: {index_digest!r}'

    # Either identifies this image: the index digest (what a tag pull records) or one of the
    # per-platform manifest digests (what a digest-pinned single-architecture pull records).
    published = _collect_manifest_digests(manifest) | {index_digest}
    assert published, f'no manifest digests found in the captured manifest: {manifest}'

    assert any(digest in running
               for digest in published), (f'the host is running {running}, which is not a digest published for this commit '
                                          f'({sorted(published)}) — the deploy did not take')


def test_live_deploy_signoff():
    """AC4 — manual sign-off on the live deployment.

    PASS requires all three: the /system/ page names the fork commit and the develop branch
    rather than an upstream release tag; the recipe list renders recipes and their images;
    and the deploy log shows a dump was taken and verified restorable *before* migrations.
    """
    verdict = _require_evidence('signoff.json')
    data = json.loads(verdict.read_text(encoding='utf-8'))

    for key in ('system_page_shows_fork_commit', 'recipes_and_images_render', 'backup_verified_before_migration'):
        assert key in data, f'{key} missing from signoff.json — the observation was not recorded'
        assert data[key] is True, f'AC4 FAIL — {key} was not observed: {data.get(key)!r}'

    # The deploy log is the independent record behind the third observation: the backup gate
    # must appear ahead of the migration step, not merely have happened at some point.
    log = _require_evidence('deploy.log').read_text(encoding='utf-8', errors='replace')
    assert 'RESTORABLE:' in log, 'the deploy log records no successful dump verification'

    backup_at = log.index('Backup gate passed')
    migrate_at = log.find('Step 4/5')
    assert migrate_at >= 0, 'the deploy log has no migration step'
    assert backup_at < migrate_at, 'the migration step ran before the backup was verified'
