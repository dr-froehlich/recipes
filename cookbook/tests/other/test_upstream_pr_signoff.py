"""Acceptance test for REQ-005 AC4 — manual sign-off on the published pull request.

AC1–AC3 prove the branch's *shape* against this repository's git history, disconfirmably and
offline. What they cannot see is the thing that actually went out: a pull request on
github.com, its checks, the CLA bot's verdict, the description a reviewer reads, and whether
issue #382 got the comment that points at it. Those live on someone else's server and are
graded by a human reading a page.

So this is a checklist grader, not a behaviour test. The System Tester opens the PR and
records what is there; this module refuses anything incomplete, self-contradictory, or still
carrying the fork's process vocabulary into a public description.

Evidence: ``signoff.json`` in the evidence dir::

    {
      "pr_url": "https://github.com/TandoorRecipes/recipes/pull/1234",
      "pr_number": 1234,
      "base_repo": "TandoorRecipes/recipes",
      "base_branch": "develop",
      "head_repo": "dr-froehlich/recipes",
      "head_branch": "readable-durations",
      "checks_green": false,
      "checks_blocked_on_approval": true,
      "local_verification": {
        "pytest": "1261 passed, 18 skipped",
        "vitest": "20 passed",
        "yarn_build": "built, 98 modules",
        "makemigrations_check": "No changes detected"
      },
      "cla_signed": false,
      "cla_requested": false,
      "files_changed": ["cookbook/models.py", "..."],
      "description": "<the full PR description as published>",
      "issue_382_comment_url": "https://github.com/TandoorRecipes/recipes/issues/382#issuecomment-..."
    }

``files_changed`` is the Files Changed tab, transcribed in full — it is what proves no fork
harness was published. ``description`` is the published text verbatim, so the checks below
grade what a reviewer actually sees rather than what was intended.
"""
import json
import os
from pathlib import Path

import pytest

BASE_REPO = 'TandoorRecipes/recipes'
BASE_BRANCH = 'develop'
HEAD_REPO = 'dr-froehlich/recipes'

# fork process vocabulary that must never appear in a public description (REQ-005 Decision 6)
FORBIDDEN_IN_DESCRIPTION = ('DevSteward', 'devsteward', 'REQ-00', 'steward ', 'acceptance criterion')

# harness paths that must not appear in the Files Changed tab
HARNESS_MARKERS = (
    'requirements/', '.devsteward/', '.claude/', 'deploy/', 'STEWARD.md', 'CLAUDE.md',
    'test_readable_time_signoff.py', 'test_openapi_client_fresh.py', 'test_upstream_pr_branch.py',
)


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation."""
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    if not raw:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-005)')
    path = Path(raw) / name
    assert path.is_file(), f'required evidence {name} was not captured into {raw}'
    return path


def test_live_signoff():
    """PASS requires a green, CLA-cleared PR whose diff and description are both clean."""
    data = json.loads(_require_evidence('signoff.json').read_text(encoding='utf-8'))

    # (a) it points where it is supposed to point
    assert data.get('base_repo') == BASE_REPO, (
        f'the pull request must target {BASE_REPO}, got {data.get("base_repo")!r}'
    )
    assert data.get('base_branch') == BASE_BRANCH, (
        f'the pull request must target the {BASE_BRANCH} branch, got {data.get("base_branch")!r}'
    )
    assert data.get('head_repo') == HEAD_REPO, (
        f'the pull request must come from the personal fork {HEAD_REPO}, got {data.get("head_repo")!r}'
    )

    url = str(data.get('pr_url', ''))
    assert url.startswith(f'https://github.com/{BASE_REPO}/pull/'), (
        f'pr_url does not look like a pull request on {BASE_REPO}: {url!r}'
    )

    # (b) green, or held at GitHub's first-time-contributor approval gate with the
    # equivalent verification recorded. Upstream's CI is guarded by
    # `if: github.repository_owner == 'TandoorRecipes'`, so a fork can never produce this
    # signal itself, and the PR's own runs sit at `action_required` until a maintainer
    # releases them. Waiting on that would park the requirement on someone else's queue.
    if data.get('checks_green') is not True:
        assert data.get('checks_blocked_on_approval') is True, (
            'the checks are not green and are not recorded as held at the first-time-'
            'contributor approval gate — a check that actually ran and went red is a fail'
        )
        local = data.get('local_verification') or {}
        for step in ('pytest', 'vitest', 'yarn_build', 'makemigrations_check'):
            assert str(local.get(step, '')).strip(), (
                f'checks are approval-gated, so local_verification.{step} must record the '
                f'equivalent run performed on the branch'
            )

    # (c) signed, or not yet requested — there is nothing to sign until the bot asks
    if data.get('cla_signed') is not True:
        assert data.get('cla_requested') is False, (
            'the contributor license agreement has been requested and is not signed — the '
            'pull request cannot be merged until it is'
        )

    # (d) nothing from the fork harness was published
    files_changed = data.get('files_changed')
    assert isinstance(files_changed, list) and files_changed, (
        'files_changed must list the Files Changed tab so the diff can be graded'
    )
    leaked = sorted({
        path for path in files_changed
        if any(marker in str(path) for marker in HARNESS_MARKERS)
    })
    assert not leaked, f'fork harness was published in the pull request: {leaked}'

    # (e) the description is a technical description, in upstream's language, offering the seams
    description = str(data.get('description', ''))
    assert len(description) >= 400, (
        'the description is too short to be the technical description the contribution '
        'guidelines ask for'
    )
    leaked_words = sorted({word for word in FORBIDDEN_IN_DESCRIPTION if word in description})
    assert not leaked_words, (
        f'the published description leaks this fork\'s process vocabulary: {leaked_words}'
    )
    assert '#382' in description, 'the description does not reference issue #382'
    assert 'vitest' in description.lower(), (
        'the description does not mention the vitest commit, so the offer to split it out is '
        'not on the page a reviewer reads'
    )
    assert 'default' in description.lower(), (
        'the description does not mention the default value, so the offer to flip it is not '
        'on the page a reviewer reads'
    )

    # (f) the five year old issue thread points at it
    comment_url = str(data.get('issue_382_comment_url', ''))
    assert '/issues/382' in comment_url and 'issuecomment' in comment_url, (
        f'issue #382 does not carry a comment linking the pull request: {comment_url!r}'
    )
