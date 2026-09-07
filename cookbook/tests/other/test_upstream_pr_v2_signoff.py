"""Acceptance test for REQ-010 AC6 — manual sign-off on the reshaped pull request.

AC3 and AC4 prove the branch's shape against this repository's git history, offline and
disconfirmably. What they cannot see is what actually went out: a pull request on github.com,
its checks, the CLA bot's verdict, the description a reviewer reads, and whether the maintainer's
closing comment on #4785 was ever answered. Those live on someone else's server and are graded
by a human reading a page.

So this is a checklist grader, not a behaviour test. It refuses anything incomplete,
self-contradictory, still carrying this fork's process vocabulary into a public description, or
still advertising the vitest commit as droppable — which REQ-010 Decision 6 rules out. The
maintainer closed #4785 for being more complex than it needed to be; a description that opens by
offering to remove the tests reads as bargaining rather than as a fix.

Evidence: ``signoff.json`` in the evidence dir::

    {
      "pr_url": "https://github.com/TandoorRecipes/recipes/pull/1234",
      "pr_number": 1234,
      "base_repo": "TandoorRecipes/recipes",
      "base_branch": "develop",
      "head_repo": "dr-froehlich/recipes",
      "head_branch": "readable-durations-v2",
      "checks_green": false,
      "checks_blocked_on_approval": true,
      "local_verification": {
        "pytest": "1303 passed, 26 skipped",
        "vitest": "14 passed",
        "yarn_build": "built",
        "makemigrations_check": "No changes detected"
      },
      "cla_signed": true,
      "cla_requested": true,
      "files_changed": ["vue3/src/utils/duration_utils.ts", "..."],
      "description": "<the full pull request description as published>",
      "issue_4785_comment_url": "https://github.com/TandoorRecipes/recipes/pull/4785#issuecomment-...",
      "issue_382_comment_url": "https://github.com/TandoorRecipes/recipes/issues/382#issuecomment-..."
    }

``files_changed`` is the Files Changed tab transcribed in full — it is what proves no backend and
no fork harness was published. ``description`` is the published text verbatim, so the checks
below grade what a reviewer actually sees rather than what was intended.
"""
import json
import os
from pathlib import Path

import pytest

BASE_REPO = 'TandoorRecipes/recipes'
BASE_BRANCH = 'develop'
HEAD_REPO = 'dr-froehlich/recipes'
HEAD_BRANCH = 'readable-durations-v2'

# the ten paths the branch is allowed to touch (REQ-010's Requirement)
ALLOWED_FILES = {
    'vue3/package.json',
    'vue3/src/components/display/RecipeCard.vue',
    'vue3/src/components/display/RecipeView.vue',
    'vue3/src/components/display/StepView.vue',
    'vue3/src/composables/useDurationDisplay.ts',
    'vue3/src/locales/en.json',
    'vue3/src/utils/duration_utils.spec.ts',
    'vue3/src/utils/duration_utils.ts',
    'vue3/vitest.config.ts',
    'vue3/yarn.lock',
}

# fork process vocabulary that must never appear in a public description
FORBIDDEN_IN_DESCRIPTION = ('DevSteward', 'devsteward', 'REQ-0', 'steward ', 'acceptance criterion', 'household')

# phrases that would re-open the offer Decision 6 withdrew
FORBIDDEN_OFFERS = ('drop it', 'dropped', 'droppable', 'single reset', 'separate PR', 'separate pull request')

# what a reviewer must be told: both threads, and that the behaviour is now unconditional
REQUIRED_REFERENCES = ('#4785', '#382')

REQUIRED_LOCAL_VERIFICATION = ('pytest', 'vitest', 'yarn_build', 'makemigrations_check')


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation."""
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    if not raw:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-010)')
    path = Path(raw) / name
    assert path.is_file(), f'required evidence {name} was not captured into {raw}'
    return path


def test_live_signoff():
    """PASS requires a correctly targeted, clean, honestly described pull request."""
    data = json.loads(_require_evidence('signoff.json').read_text(encoding='utf-8'))

    # (a) it points where it is supposed to point
    assert data.get('base_repo') == BASE_REPO, f'must target {BASE_REPO}, got {data.get("base_repo")!r}'
    assert data.get('base_branch') == BASE_BRANCH, f'must target {BASE_BRANCH}, got {data.get("base_branch")!r}'
    assert data.get('head_repo') == HEAD_REPO, f'must come from {HEAD_REPO}, got {data.get("head_repo")!r}'
    assert data.get('head_branch') == HEAD_BRANCH, (
        f'must come from {HEAD_BRANCH} — #4785\'s branch is left at the commit it was reviewed '
        f'at (REQ-010 Decision 5); got {data.get("head_branch")!r}'
    )
    assert data.get('pr_url', '').startswith(f'https://github.com/{BASE_REPO}/pull/'), (
        f'pr_url must be a pull request on {BASE_REPO}; got {data.get("pr_url")!r}'
    )

    # (b) checks are green, or held at GitHub's first-time-contributor gate with the equivalent
    # verification recorded — upstream's workflows are owner-gated, so a fork never runs them
    if not data.get('checks_green'):
        assert data.get('checks_blocked_on_approval') is True, (
            'checks are not green and are not recorded as held at the approval gate — a check '
            'that actually ran and went red fails this criterion'
        )
        verification = data.get('local_verification') or {}
        missing = [key for key in REQUIRED_LOCAL_VERIFICATION if not verification.get(key)]
        assert not missing, (
            f'checks never ran, so the equivalent local verification must be recorded; missing '
            f'{missing}'
        )

    # (c) the CLA is signed, or the bot has not asked
    if data.get('cla_requested'):
        assert data.get('cla_signed') is True, (
            'the CLA bot has requested the agreement and it is unsigned — only the owner can '
            'sign it, at cla-assistant.io/TandoorRecipes/recipes'
        )

    # (d) the diff is the contribution and nothing else
    files_changed = data.get('files_changed')
    assert files_changed, 'files_changed must transcribe the Files Changed tab in full'
    unexpected = set(files_changed) - ALLOWED_FILES
    assert not unexpected, (
        f'the published pull request carries paths outside the manifest: {sorted(unexpected)}. A '
        f'backend path, a migration or a generated client file is precisely what #4785 was '
        f'closed over'
    )

    # (e) the description is honest, complete, and free of this fork's vocabulary
    description = data.get('description') or ''
    assert description.strip(), 'description must be captured verbatim'

    leaked = [term for term in FORBIDDEN_IN_DESCRIPTION if term in description]
    assert not leaked, f'the public description leaks fork process vocabulary: {leaked}'

    offered = [phrase for phrase in FORBIDDEN_OFFERS if phrase in description.lower()]
    assert not offered, (
        f'the description still advertises the vitest commit as removable ({offered}); Decision 6 '
        f'keeps the seam but withdraws the offer'
    )

    missing_refs = [ref for ref in REQUIRED_REFERENCES if ref not in description]
    assert not missing_refs, f'the description does not reference {missing_refs}'

    assert 'unconditional' in description.lower() or 'no preference' in description.lower(), (
        'the description must say plainly that the behaviour is now unconditional — that is the '
        'change the maintainer asked for'
    )

    # (f) both threads were answered
    for key, thread in (('issue_4785_comment_url', '4785'), ('issue_382_comment_url', '382')):
        url = data.get(key)
        assert url and thread in url, f'{key} must link the comment left on #{thread}; got {url!r}'
