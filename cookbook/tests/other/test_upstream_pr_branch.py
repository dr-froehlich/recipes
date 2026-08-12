"""Acceptance tests for REQ-005 — the shape of the upstream pull request branch.

The deliverable of REQ-005 is a branch, not a behaviour: ``readable-durations``, cut from
``upstream/develop``, carrying REQ-003's work and nothing else. "Nothing else" is the part
that needs a test. This fork's harness — the DevSteward ledger, the requirements tree, the
deploy scripts, CLAUDE.md — sits in the same working tree as the contribution, and a single
careless ``git add`` would publish it to a public repository under the owner's name. That
mistake is silent, irreversible in the sense that matters (it is in the PR history the
moment it is pushed), and invisible in a diff that is already 400 lines of regenerated
lockfile.

So the oracle here is this repository's own git history, which makes these coupled,
self-contained checks rather than anything the lab needs to produce.

**Required environment.** They read git state that a clean checkout does not have: the
``upstream`` remote must exist and be fetched, and the branch must be present locally. When
either is missing the tests **skip**. That is deliberate and it cuts both ways. While
REQ-005 is being verified these are *named* acceptance criteria, and the engine fails the
gate on a skipped named test — skip is not green, so the branch cannot go missing and pass.
Afterwards they are ordinary members of the full suite, where a skip is legal, so the suite
stays green on a machine that has never fetched upstream or once the merged branch is
deleted.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

BRANCH = 'readable-durations'
BASE = 'upstream/develop'

# the vitest introduction, which the PR description offers to split out — it is the branch
# tip so that dropping it is a single reset (REQ-005 Decision 2)
VITEST_FILES = {
    'vue3/package.json',
    'vue3/src/utils/duration_utils.spec.ts',
    'vue3/vitest.config.ts',
    'vue3/yarn.lock',
}

# everything the feature commit is allowed to touch
FEATURE_FILES = {
    'cookbook/migrations/0243_userpreference_use_readable_time.py',
    'cookbook/models.py',
    'cookbook/serializer.py',
    'cookbook/tests/api/test_api_userpreference.py',
    'vue3/src/components/display/RecipeCard.vue',
    'vue3/src/components/display/RecipeView.vue',
    'vue3/src/components/display/StepView.vue',
    'vue3/src/components/settings/CosmeticSettings.vue',
    'vue3/src/composables/useDurationDisplay.ts',
    'vue3/src/locales/en.json',
    'vue3/src/openapi/models/PatchedUserPreference.ts',
    'vue3/src/openapi/models/UserPreference.ts',
    'vue3/src/utils/duration_utils.ts',
}

MANIFEST = FEATURE_FILES | VITEST_FILES

# fork harness that lives in the same tree and must never reach a public repository
HARNESS_PREFIXES = ('requirements/', '.devsteward/', '.claude/', '.github/', 'deploy/')
HARNESS_FILES = {
    'CLAUDE.md',
    'STEWARD.md',
    '.dockerignore',
    '.gitignore',
    'mkdocs.yml',
    'cookbook/tests/other/test_baseline.py',
    'cookbook/tests/other/test_fork_delivery.py',
    'cookbook/tests/other/test_openapi_client_fresh.py',
    'cookbook/tests/other/test_readable_time_signoff.py',
    'cookbook/tests/other/test_upstream_pr_branch.py',
}


def git(*args):
    """Run a git command in this repository and return its stdout, or None if it failed."""
    result = subprocess.run(
        ('git',) + args, cwd=REPO_ROOT, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def require_branch_and_base():
    """Skip unless both the PR branch and the fetched upstream base are present."""
    if git('rev-parse', '--verify', f'{BRANCH}^{{commit}}') is None:
        pytest.skip(f'branch {BRANCH} is not present — nothing to check')
    if git('rev-parse', '--verify', f'{BASE}^{{commit}}') is None:
        pytest.skip(f'{BASE} is not present — run `git fetch upstream`')


def changed_files(rev_range):
    output = git('diff', '--name-only', rev_range)
    return {line for line in (output or '').splitlines() if line}


def test_branch_contains_only_the_contribution():
    """The branch is cut from upstream's tip and carries no fork harness (REQ-005 AC1)."""
    require_branch_and_base()

    # cut from upstream's tip, not from this fork's develop
    merge_base = git('merge-base', BASE, BRANCH)
    assert merge_base == git('rev-parse', f'{BASE}^{{commit}}'), (
        f'{BRANCH} is not based on {BASE} — it must be cut from a freshly fetched '
        f'upstream tip, or the PR will carry this fork\'s unrelated history'
    )

    touched = changed_files(f'{BASE}..{BRANCH}')
    assert touched, f'{BRANCH} changes nothing against {BASE}'

    harness = {
        path for path in touched
        if path in HARNESS_FILES or path.startswith(HARNESS_PREFIXES)
    }
    assert not harness, (
        f'fork harness would be published in the pull request: {sorted(harness)}'
    )

    unexpected = touched - MANIFEST
    assert not unexpected, (
        f'{BRANCH} touches files outside the agreed manifest: {sorted(unexpected)}'
    )

    # the migration has to be free on upstream's tip or it collides on merge
    added_migrations = {
        path for path in touched if path.startswith('cookbook/migrations/')
    }
    upstream_migrations = {
        Path(path).name.split('_')[0]
        for path in (git('ls-tree', '--name-only', BASE, 'cookbook/migrations/') or '').splitlines()
        if path.endswith('.py')
    }
    for path in added_migrations:
        number = Path(path).name.split('_')[0]
        assert number not in upstream_migrations, (
            f'migration {number} already exists on {BASE} — renumber {path} before opening '
            f'the pull request'
        )


def test_commits_are_separable():
    """The vitest introduction is the branch tip and drops with one reset (REQ-005 AC2)."""
    require_branch_and_base()

    commits = (git('rev-list', f'{BASE}..{BRANCH}') or '').splitlines()
    assert len(commits) == 2, (
        f'expected two commits on {BRANCH} — the feature and the vitest introduction — '
        f'found {len(commits)}'
    )

    tip, feature = commits[0], commits[1]

    tip_files = changed_files(f'{tip}^..{tip}')
    assert tip_files == VITEST_FILES, (
        f'the branch tip must contain exactly the vitest introduction so it can be dropped '
        f'with a single reset; it touches {sorted(tip_files)}'
    )

    feature_files = changed_files(f'{feature}^..{feature}')
    overlap = feature_files & VITEST_FILES
    assert not overlap, (
        f'the feature commit also touches vitest files {sorted(overlap)} — dropping the '
        f'test tooling would no longer be a clean reset'
    )


def test_default_flipped_and_english_only():
    """The PR ships the preference off, and touches only the English catalog (REQ-005 AC3)."""
    require_branch_and_base()

    branch_model = git('show', f'{BRANCH}:cookbook/models.py')
    assert 'use_readable_time = models.BooleanField(default=False)' in branch_model, (
        'the pull request must default use_readable_time to False so no existing upstream '
        'user\'s recipe pages change on upgrade (REQ-005 Decision 3)'
    )

    fork_model = git('show', 'develop:cookbook/models.py')
    assert 'use_readable_time = models.BooleanField(default=True)' in fork_model, (
        'this fork keeps the preference on by default (REQ-003 Decision 3); the flip belongs '
        'to the pull request branch alone'
    )

    catalogs = {
        path for path in changed_files(f'{BASE}..{BRANCH}')
        if path.startswith('vue3/src/locales/')
    }
    assert catalogs == {'vue3/src/locales/en.json'}, (
        f'only the English catalog may be touched — translations go through Weblate '
        f'(docs/contribute/translations.md); found {sorted(catalogs)}'
    )
