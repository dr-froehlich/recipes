# Plan 0005 — REQ-005's develop checkpoint: the upstream PR for readable durations

> Authored 2026-08-12. A plan is a thinking document: how a chunk of work will be
> approached, the alternatives weighed, the sequence. It is not a contract (REQs are).

## Context

Advances [REQ-005](../REQ-005.md) — REQ-003's readable durations, offered to
`TandoorRecipes/recipes` as a pull request that contains the contribution and nothing else.

This is the first work in this fork whose deliverable lives outside the machine. It is also
the first `develop: split` REQ, so the design below was reviewed with the owner before any
code was written; three forks that only appeared once the branch was real are recorded under
*Forks resolved at review*.

Shape of the work: one branch cut from upstream's tip, a file manifest split into ship and
do-not-ship, two commits, one dependency lock regenerated rather than copied, a default
value flipped through five places, three git-shape acceptance tests, and a publication
sequence that is gated on the owner.

## The branch point

`origin` is `dr-froehlich/recipes` (push enabled); `upstream` is `TandoorRecipes/recipes`
(fetch-only, `no_push`). The PR goes from a branch on `origin` to `upstream:develop`.

Merge base with upstream is `9f6d43b95`. Our `develop` is **21 ahead, 10 behind**. The 10
upstream commits we lack matter more than the count suggests — they touch
`vue3/package.json` (vuetify `^3.11.8` → `^3.13.1`) and `vue3/yarn.lock`, which are two of
the four files our vitest commit also touches.

**This kills the obvious approach.** `git checkout develop -- <path>` takes our *whole file*,
so for `package.json` it would silently revert upstream's vuetify bump, and for `yarn.lock`
it would revert far more. Whole-file checkout is only safe for the files upstream has not
touched — which, checked file by file, is every contribution file except those two.

So:

- **`package.json`** — apply our delta by hand onto upstream's version. The two deltas are
  disjoint hunks (they bumped a dependency; we added a script and a devDependency), so
  nothing is lost either way.
- **`yarn.lock`** — **regenerate** with `yarn install` on the branch, after the
  devDependency is added. A copied lock would encode our vuetify version. This is the one
  file in the PR that must be produced rather than transplanted.
- **everything else** — whole-file checkout from `develop` is safe and exact.

Migration numbering: `0243` is free on upstream's tip (they top out at
`0242_space_household_setup_completed`, which is exactly our migration's declared
dependency), so no renumbering is needed. Re-checked at branch time rather than trusted from
REQ-005's Context, which is what that paragraph asked for.

## The manifest

**Ships** — the whole of the contribution:

| File | Commit | Source |
|---|---|---|
| `cookbook/migrations/0243_userpreference_use_readable_time.py` | 1 | checkout, then default flipped |
| `cookbook/models.py` | 1 | checkout, then default flipped |
| `cookbook/serializer.py` | 1 | checkout |
| `cookbook/tests/api/test_api_user_preference.py` | 1 | checkout, then default assertions flipped, docstring sanitized |
| `vue3/src/utils/duration_utils.ts` | 1 | checkout, then param default flipped |
| `vue3/src/composables/useDurationDisplay.ts` | 1 | checkout, then `?? true` flipped |
| `vue3/src/components/display/{RecipeView,RecipeCard,StepView}.vue` | 1 | checkout |
| `vue3/src/components/settings/CosmeticSettings.vue` | 1 | checkout |
| `vue3/src/locales/en.json` | 1 | checkout |
| `vue3/src/openapi/models/{UserPreference,PatchedUserPreference}.ts` | 1 | checkout |
| `vue3/package.json` | 2 | delta applied onto upstream's version |
| `vue3/vitest.config.ts` | 2 | checkout |
| `vue3/src/utils/duration_utils.spec.ts` | 2 | checkout, then one test updated |
| `vue3/yarn.lock` | 2 | **regenerated** |

**Does not ship** — fork harness, every one of these present in REQ-003's commits or the
surrounding fork work:

`requirements/`, `.devsteward/`, `.claude/`, `deploy/`, `STEWARD.md`, `CLAUDE.md`,
`.dockerignore`, `.gitignore`, `mkdocs.yml`, `.github/workflows/build-docker.yml`,
`cookbook/tests/other/test_baseline.py`, `cookbook/tests/other/test_fork_delivery.py`,
`cookbook/tests/other/test_data/fork_delivery/restorable.dump`,
`cookbook/tests/other/test_readable_time_signoff.py` (a DevSteward evidence grader),
`cookbook/tests/other/test_openapi_client_fresh.py` (see below).

## Forks resolved at review

Three things intake could not have known, decided with the owner before building.

**1. The default flip is not one line — so it stops being its own commit.** REQ-005
Decision 2 planned three commits with the flip isolated. But Django tracks a field's
`default` in migration state, so `models.py` and the migration's `AddField` must move
together or `makemigrations --check` fails. And the flip's true surface turned out to be
**five** places, not one: the model, the migration, two assertions in the API test, and the
frontend's `?? true` fallback in `useDurationDisplay.ts`. A commit that flips a default in
five files, immediately after the commit that set it, reads as indecision rather than as a
seam. Resolved: **two commits** — the feature authored OFF from the start, then vitest —
with the default offered back in the PR description as a one-line change. A one-line offer
is a more flexible seam than a commit, and `git reset --hard HEAD~1` is now the whole
"drop the tests" operation.

**2. The test script exports our harness's problem.** REQ-003's script is
`yarn install --frozen-lockfile --silent && vitest run`; the install prefix exists so this
fork's acceptance gate hard-fails instead of silently skipping when `node_modules` is
absent. Upstream has no such gate and would reasonably ask why a test script installs
dependencies. Resolved: the PR ships plain **`vitest run`**; the fork keeps its own form.

**3. `test_openapi_client_fresh.py` stays home.** It asserts the generated TypeScript client
exposes `useReadableTime` by string-matching generated files. The hole it closes is real, but
it is *our* hole — CLAUDE.md's warning that regenerating without the enterprise plugins
strips ~40 model files. Upstream regenerates as part of a documented workflow and has no
such trap, and a bespoke freshness test for one field of one serializer invites a review
question unrelated to duration formatting. Resolved: dropped from the PR, kept in the fork.

## The default, flipped through five places

REQ-005 Decision 3: OFF upstream, ON in this fork. On the branch:

1. `models.py` — `use_readable_time = models.BooleanField(default=False)`
2. the migration's `AddField(..., field=models.BooleanField(default=False))`
3. `test_api_user_preference.py::test_readable_time_defaults_on` → asserts `is False`, renamed
4. `test_api_user_preference.py::test_readable_time_round_trips_through_the_api` — the
   opening GET expects `False`, and the PATCH writes `True`
5. `useDurationDisplay.ts` — `?? true` → `?? false`

Plus `duration_utils.ts`'s own parameter default, `useReadableTime: boolean = true` →
`= false`. This one is a judgement call the repo already answers: the sibling preference's
helper is `calculateFoodAmount(amount, factor, useFractions: boolean = false)`. On a branch
where the feature is opt-in, a pure function that opts in when unasked is the odd one out.
The spec's `defaults to readable english output` case moves with it.

## Tests

Three new `regression` criteria, all reading this repository's own git state — the oracle is
coupled (our history), the environment requirement is the `upstream` remote being fetched,
recorded in REQ-005's Notes. One module, `cookbook/tests/other/test_upstream_pr_branch.py`:

- **AC1** the branch's merge base is `upstream/develop`; its diff against `upstream/develop`
  touches no harness path and nothing outside the manifest; its migration collides with no
  migration number on upstream's tip.
- **AC2** the vitest commit touches only the four vitest files and nothing else, so it can
  be dropped with a reset.
- **AC3** the branch ships `default=False` while `develop` ships `default=True`, and
  `vue3/src/locales/en.json` is the only catalog it touches.

AC2 as written in REQ-005 also required the default flip to be its own commit — that clause
goes with fork 1 above, and the REQ is amended in the same commit as this plan.

A fourth, `manual`, signs off the published PR from its GitHub page.

## Sequence

1. Plan + REQ amendment (this).
2. Cut `readable-durations` from `upstream/develop`; build the two commits; regenerate the
   lock.
3. Verify **on the branch**: full pytest suite, `vitest run`, `makemigrations --check`,
   and the flake8/isort/yapf/prettier gate `guidelines.md` requires.
4. Back on `develop`: write the three git-shape tests, run them, `steward lint`.
5. **Attended review** — walk the owner through the diff and the drafted PR description.
6. Owner signs the CLA. Then, on the owner's go-ahead: push the branch to `origin`, confirm
   the fork's CI is green, open the PR, comment on #382.
7. `steward checkpoint REQ-005 develop`.

Step 6 is the only irreversible part and is gated twice — once by the review, once by the
go-ahead. Nothing reaches GitHub before both.

## Risks

- **`yarn install` rewrites the shared `vue3/node_modules`.** It is gitignored and shared
  across branches, so after switching back to `develop` the tree holds the branch's
  dependency set. Re-run `yarn install` on `develop` before the checkpoint, or REQ-003's
  vitest AC runs against upstream's vuetify.
- **Upstream moves under us.** They are 10 commits ahead now and merge continuously; a long
  gap between cutting the branch and opening the PR invites a rebase. Mitigation: steps 2–6
  happen in one session.
- **The branch is a working artifact on `develop`'s repo.** CLAUDE.md forbids feature
  branches for fork work; this branch is not fork work but the deliverable itself, and it
  never merges into `develop`. Returning to `develop` before the checkpoint is explicit in
  the sequence for that reason.
