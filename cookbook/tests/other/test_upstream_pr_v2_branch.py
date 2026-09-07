"""Acceptance tests for REQ-010 — the shape of the reshaped upstream pull request branch.

Upstream accepted the feature on #4785 and declined its mechanism: "I do not think we need the
user preference. Just show the times in a human readable format." The reshaped branch is
therefore **frontend only**, and that is the property worth a test. A single stray
``git checkout develop -- cookbook/...`` would put back the migration, the model field and the
serializer entry that were the whole reason the first pull request was closed — and it would do
it silently, inside a diff already 380 lines of regenerated lockfile.

So where REQ-005's equivalent module asked "does the branch carry fork harness?", this one also
asks the sharper question: **does it touch the backend at all?** It must not. No ``cookbook/``
path, no migration, no regenerated client, and not one occurrence of the preference's name
anywhere in the diff.

The oracle is this repository's own git history, which makes these coupled, self-contained
checks rather than anything a lab has to produce.

**On comparing against a moving target.** These read the branch's own merge base, never
``upstream/develop``'s current tip. REQ-005's module learned that the hard way: written when the
fork was ten commits behind, it reported a foreign merge base and six Weblate-updated catalogs
as soon as upstream moved on — 129 commits later. A finished branch is compared against the
commit it was cut from, which does not move.

**Required environment.** They read git state a clean checkout does not have: the ``upstream``
remote fetched, and the branch present locally. When either is missing they **skip**. That is
deliberate and cuts both ways — while REQ-010 is being verified these are *named* acceptance
criteria and the engine fails the gate on a skipped named test, so the branch cannot go missing
and pass; afterwards they are ordinary suite members where a skip is legal, so the suite stays
green on a machine that has never fetched upstream.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

BRANCH = 'readable-durations-v2'
BASE = 'upstream/develop'

# REQ-005's branch, the one pull request #4785 was reviewed at. REQ-010 Decision 5 opens a new
# pull request from a new branch precisely so this one can be left alone: force-pushing it would
# rewrite the diff attached to a closed review into something the maintainer never saw.
REVIEWED_BRANCH = 'readable-durations'
REVIEWED_TIP = '3303c2ad3ab36f19446bdeced8b1bb2f2f265822'

# the vitest introduction, kept as the branch tip so it drops with a single reset
VITEST_FILES = {
    'vue3/package.json',
    'vue3/src/utils/duration_utils.spec.ts',
    'vue3/vitest.config.ts',
    'vue3/yarn.lock',
}

# everything the feature commit is allowed to touch — six frontend files, no backend at all
FEATURE_FILES = {
    'vue3/src/components/display/RecipeCard.vue',
    'vue3/src/components/display/RecipeView.vue',
    'vue3/src/components/display/StepView.vue',
    'vue3/src/composables/useDurationDisplay.ts',
    'vue3/src/locales/en.json',
    'vue3/src/utils/duration_utils.ts',
}

MANIFEST = FEATURE_FILES | VITEST_FILES

# paths whose presence would mean the branch reached somewhere it must not: fork harness, and —
# new in REQ-010 — the backend and the generated client the maintainer asked to be rid of
FORBIDDEN_PREFIXES = (
    'cookbook/', 'vue3/src/openapi/', 'requirements/', '.devsteward/', '.claude/', '.github/', 'deploy/',
)
FORBIDDEN_FILES = {'CLAUDE.md', 'STEWARD.md', '.dockerignore', '.gitignore', 'mkdocs.yml'}

# the preference's name in each of the spellings it had; none may survive anywhere in the diff
PREFERENCE_NAMES = ('use_readable_time', 'useReadableTime', 'Use_Readable_Time')


def git(*args):
    """Run a git command in this repository and return its stdout, or None if it failed."""
    result = subprocess.run(('git',) + args, cwd=REPO_ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def git_ok(*args):
    """Run a git command for its exit status alone (--is-ancestor prints nothing)."""
    return subprocess.run(('git',) + args, cwd=REPO_ROOT, capture_output=True, text=True).returncode == 0


def require_branch_and_base():
    """Skip unless both the PR branch and the fetched upstream base are present."""
    if git('rev-parse', '--verify', f'{BRANCH}^{{commit}}') is None:
        pytest.skip(f'branch {BRANCH} is not present — nothing to check')
    if git('rev-parse', '--verify', f'{BASE}^{{commit}}') is None:
        pytest.skip(f'{BASE} is not present — run `git fetch upstream`')


def branch_base():
    """The upstream commit the branch was cut from — fixed, unlike upstream's tip."""
    return git('merge-base', BASE, BRANCH)


def changed_files(rev_range):
    return {line for line in (git('diff', '--name-only', rev_range) or '').splitlines() if line}


def test_branch_contains_only_the_contribution():
    """The branch is frontend-only, carries no harness, and never names the preference (AC3)."""
    require_branch_and_base()

    base = branch_base()
    assert base, f'{BRANCH} and {BASE} share no history at all'
    assert git_ok('merge-base', '--is-ancestor', base, f'{BASE}^{{commit}}'), (
        f'{BRANCH} was cut from {base}, which is not an ancestor of {BASE} — it must branch '
        f'from upstream, not from this fork'
    )

    touched = changed_files(f'{base}..{BRANCH}')
    assert touched, f'{BRANCH} changes nothing against its base'

    forbidden = {
        path for path in touched
        if path in FORBIDDEN_FILES or path.startswith(FORBIDDEN_PREFIXES)
    }
    assert not forbidden, (
        f'the pull request would carry paths it must not: {sorted(forbidden)}. The backend and '
        f'the generated client are exactly what #4785 was closed over; fork harness must never '
        f'reach a public repository at all'
    )

    unexpected = touched - MANIFEST
    assert not unexpected, (
        f'{BRANCH} touches files outside the agreed manifest: {sorted(unexpected)}'
    )

    # no migration, stated separately from the cookbook/ sweep because it is the specific thing
    # a careless replay of REQ-003's commit would reintroduce
    migrations = {path for path in touched if '/migrations/' in path}
    assert not migrations, f'the branch adds a migration: {sorted(migrations)}'

    # English only — translations go through Weblate (docs/contribute/translations.md)
    catalogs = {path for path in touched if path.startswith('vue3/src/locales/')}
    assert catalogs == {'vue3/src/locales/en.json'}, (
        f'only the English catalog may be touched; found {sorted(catalogs)}'
    )

    # the preference is gone, not merely defaulted off: its name appears nowhere in the diff
    diff = git('diff', f'{base}..{BRANCH}') or ''
    present = [name for name in PREFERENCE_NAMES if name in diff]
    assert not present, (
        f'the branch still mentions {present} — upstream declined the preference outright, so '
        f'nothing in the pull request should name it'
    )


def test_commits_are_separable():
    """The vitest introduction is the branch tip, and #4785's branch is untouched (AC4)."""
    require_branch_and_base()

    commits = (git('rev-list', f'{branch_base()}..{BRANCH}') or '').splitlines()
    assert len(commits) == 2, (
        f'expected two commits on {BRANCH} — the formatter and the vitest introduction — '
        f'found {len(commits)}'
    )

    tip, feature = commits[0], commits[1]

    tip_files = changed_files(f'{tip}^..{tip}')
    assert tip_files == VITEST_FILES, (
        f'the branch tip must contain exactly the vitest introduction so it can be dropped with '
        f'a single reset; it touches {sorted(tip_files)}'
    )

    feature_files = changed_files(f'{feature}^..{feature}')
    overlap = feature_files & VITEST_FILES
    assert not overlap, (
        f'the feature commit also touches vitest files {sorted(overlap)} — dropping the test '
        f'tooling would no longer be a clean reset'
    )

    # the reviewed branch is left exactly where the maintainer saw it
    if git('rev-parse', '--verify', f'{REVIEWED_BRANCH}^{{commit}}') is not None:
        assert git('rev-parse', REVIEWED_BRANCH) == REVIEWED_TIP, (
            f'{REVIEWED_BRANCH} has moved; #4785 is closed and its diff must keep showing what '
            f'was actually reviewed (REQ-010 Decision 5)'
        )
