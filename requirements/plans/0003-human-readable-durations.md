# Plan 0003 — REQ-003's develop checkpoint: human-readable durations

> Authored 2026-08-12. A plan is a thinking document: how a chunk of work will be
> approached, the alternatives weighed, the sequence. It is not a contract (REQs are).

## Context

Advances [REQ-003](../REQ-003.md) — recipe and step durations rendered as hours and minutes
instead of a flat minute count, behind a per-user preference that defaults on.

The REQ already did the hard thinking: the format rule (Decision 1, no day rollover), the
preference shape (Decision 2, mirroring `use_fractions`), the default (Decision 3, on), the
introduction of vitest (Decision 4), one shared conversion (Decision 5), no server-side
formatting (Decision 6) and the hardcoded-`min` fix (Decision 7). This plan is therefore
mostly about *how*, plus the five smaller forks that only showed up once the code was open.

Shape of the work: one model field and its migration, one serializer entry, a surgical
regeneration of the API client, a pure formatter module, a composable that binds it to the
preference and the locale, four call sites, one checkbox, three translation keys, a test
runner that did not exist, and three test modules.

## Approach

### Backend — the preference

`UserPreference.use_readable_time = models.BooleanField(default=True)`, next to
`use_fractions`, plus migration `0243_userpreference_use_readable_time`, plus the field name
in `UserPreferenceSerializer.Meta.fields`. That is the whole server change; REQ-003
Decision 6 keeps formatting off the server.

**Fork A — no environment-variable default.** `use_fractions` carries a second mechanism:
`FRACTION_PREF_DEFAULT` in `recipes/settings.py`, re-applied in `UserPreference.save()` on
create, so a hosted operator can set the default for new accounts. Not copied. The model
default *is* the household's answer (Decision 3), an env var would be a second place for the
same truth, and the `save()` override is upstream code this fork would rather not grow.
Rejected: `READABLE_TIME_PREF_DEFAULT` — a truer "field-for-field" mirror of Decision 2, but
it buys a knob nobody on this instance will turn.

### The generated client — regenerate, then keep two files

`scripts/generate_api_client.py` needs `openapi-generator-cli` (Java) on PATH and the dev
server up on :8000. Two things about running it here:

- It imports `recipes.settings`, so it needs `PYTHONPATH=<repo root>` when the venv is not
  the ambient interpreter.
- **The committed client was generated on a checkout that had the enterprise and open-data
  plugins installed.** This checkout has no `recipes/plugins/` at all, so a straight
  regeneration *deleted 40 model files* (`Enterprise*`, `OpenData*`, `Stripe*`, their
  paginated and patched variants) and cut `apis/ApiApi.ts` from 8649 lines to 2948.

**Fork B — how to regenerate without that collateral damage.** Chosen: regenerate, then
`git checkout -- vue3/src/openapi` and restore only `models/UserPreference.ts` and
`models/PatchedUserPreference.ts`, whose diffs were verified to be exactly the six lines the
new field adds. Rejected: committing the full regeneration (breaks every plugin import and
is unreviewable); installing the plugins locally to regenerate faithfully (the enterprise
plugin is not in this repository). The finding is recorded in the AC3 test's module
docstring and in `CLAUDE.md`, because the next person to regenerate will hit it blind.

### Frontend — a pure formatter and a thin composable

Two modules rather than one, which is the one place this plan spends a file it could have
saved:

- `vue3/src/utils/duration_utils.ts` — `formatDuration(minutes, useReadableTime, labels)`.
  **Zero imports.** Below 60 minutes, or with the preference off, it returns
  `` `${minutes} ${labels.minute}` `` — today's rendering, unchanged. From 60 up it returns
  `H h` plus ` M min` when the remainder is non-zero. `null`/`undefined`/`NaN` return the
  empty string; negatives fall through the `< 60` branch and render as minutes; nothing
  throws.
- `vue3/src/composables/useDurationDisplay.ts` — reads
  `userSettings.useReadableTime ?? true` and passes `t('h')` / `t('min')` as the labels.

**Fork C — why the split.** The composable has to import the user-preference store, which
transitively pulls vuetify, vue-router and the whole `@/openapi` barrel. Keeping the tested
module free of that chain means AC1 can never redden because of app wiring it does not test.
One extra file, in an established `composables/` directory, for a permanently hermetic unit
test.

The `?? true` fallback matters: the store caches `userSettings` in localStorage, so a client
that last synced before this field existed would otherwise read `undefined` and silently
fall back to raw minutes.

### The unit labels

**Fork D — where `h` comes from.** The existing `Hour`/`Hours`/`Day`/`Days` keys (added by
upstream PR #3778 for the running timer) are long forms — German "Stunde"/"Stunden" — and
would render "72 Hours" where the REQ's format table says `72 h`. Chosen: a new `"h": "h"`
key in `vue3/src/locales/en.json`, the exact sibling of the existing `"min": "min"` that
`RecipeView` already used, plus `Use_Readable_Time` and `Use_Readable_Time_Help` for the
checkbox. **English only** — `CLAUDE.md` forbids hand-editing the other catalogs, they come
from Weblate, and until German gets a short form a German user sees `72 h`, which is the
same symbol German uses anyway. Rejected: reusing `Hours` (wrong output, fails AC1);
hand-adding `"h": "Std"` to `de.json` (would be overwritten by Weblate and breaks the
project rule).

### The call sites

Four read-only displays, all rendered through `displayDuration(...)`:

| File | Was | Now |
|---|---|---|
| `RecipeView.vue:43,47` (mobile) | `{{ recipe.workingTime }} min` — hardcoded, untranslatable | `{{ displayDuration(recipe.workingTime) }}` (Decision 7) |
| `RecipeView.vue:98,102` (desktop) | `{{ recipe.workingTime }} {{ $t('min') }}` | same call |
| `RecipeCard.vue:32` | `{{ recipe.workingTime! + recipe.waitingTime! }}` — a bare number | same call, so the chip gains a unit |
| `StepView.vue:12` | `{{ step.time }}` | same call |

A sweep for `workingTime`/`waitingTime`/`step.time` across `vue3/src` found nothing else
read-only: the remaining hits are the three editors (`RecipeEditor`, `StepEditor`,
`BatchEditRecipeDialog`), which keep plain minute inputs, and `Timer.vue`, which the REQ
puts out of scope. The card fix covers the meal-plan and horizontal recipe windows, which
reuse it.

The card also gets a small free correctness win: `workingTime! + waitingTime!` is `NaN` when
a recipe has no waiting time, and the chip used to print `NaN`. `formatDuration` renders
that as nothing.

The checkbox goes into `CosmeticSettings.vue` directly under "Use Fractions", which is where
Decision 2 said it belongs.

### Test runner (Decision 4)

`vitest@4.1.10` as a dev-only devDependency, and
`"test": "yarn install --frozen-lockfile --silent && vitest run"`. Two deliberate halves:

- `run`, because bare `vitest` watches in a TTY and would hang the gate.
- the `yarn install` prefix, because `vue3/node_modules` is gitignored. The engine's capture
  check (REQ-063) extracts the *recorded commit* into a clean tree and re-runs the named
  acceptance tests there; a bare `vitest run` exits 127 in that tree, which is exactly the
  honest answer — AC1 as first written could only pass on a workstation that happened to
  have run `yarn install`. Self-preparing the dependencies from the committed `yarn.lock`
  makes the criterion reproducible from the commit alone, and costs about a second once the
  cache is warm. Rejected: rewriting AC1's `test:` command in the REQ (the criterion was
  right; its environment assumption was the bug), and committing `node_modules`.

**Fork E — configuration.** A standalone `vue3/vitest.config.ts` (which takes precedence
over `vite.config.ts`) with just the `@` alias, `environment: 'node'` and
`include: ['src/**/*.spec.ts']`. Loading the app's vite config would drag in vuetify, the PWA
plugin and the `virtual:locale-coverage` plugin to test a pure function. Rejected:
`test:` block inside `vite.config.ts` (fewer files, much more surface); jsdom (nothing here
touches a DOM).

Environment cost, called out in the REQ's Notes: Node ≥ 20.19 (this workstation now has
22.22.1), yarn — installed globally via npm, it was absent — and `yarn --cwd vue3 install`.

### Tests

| AC | Where | What it pins |
|---|---|---|
| AC1 | `vue3/src/utils/duration_utils.spec.ts` (20 cases) | every row of the REQ's format table, the same inputs with the preference off, 0/null/undefined/negative/NaN/Infinity, and that the labels are injected rather than inlined |
| AC2 | `cookbook/tests/api/test_api_user_preference.py` | the default on a newly created preference, the GET/PATCH round-trip including persistence, and that one user's choice leaves another's alone |
| AC3 | `cookbook/tests/other/test_openapi_client_fresh.py` | the serializer serves the field **and** both generated models type it, read it and send it — fails in both directions |
| AC4 | `cookbook/tests/other/test_readable_time_signoff.py` | four booleans in `signoff.json`, graded by `steward validate REQ-003`; skips without `DEVSTEWARD_EVIDENCE_DIR`, hard-fails once it is set |

**Fork F — a second user-preference API test file.** AC2 names
`cookbook/tests/api/test_api_user_preference.py`; upstream already has
`test_api_userpreference.py` (no underscore) in the same directory. Kept as the REQ names
it, rather than appending to upstream's file and amending the AC: a fork-local test module
can never conflict on an upstream rebase, which is REQ-001 Decision 2 and the same choice
REQ-002 made with `test_fork_delivery.py`. The cost is two near-identically named files, so
the new one says why in its docstring.

## Sequence

1. Toolchain: yarn, `yarn install`, vitest, `test` script, `vitest.config.ts`. ✅
2. Model field + migration + serializer entry. ✅
3. Regenerate the client, keep the two model files (fork B). ✅
4. `duration_utils.ts` + spec (AC1), `useDurationDisplay.ts`. ✅
5. Four call sites + the checkbox + three en.json keys. ✅
6. AC2/AC3/AC4 test modules; `yarn build` to typecheck the wiring. ✅
7. `steward checkpoint REQ-003 develop` — green develop gate commits on `develop`; the flip
   to `done` waits for validate, because AC4 is `manual`.
8. Push, so CI builds the arm64 image the System Tester's deploy will pull.

## What the deploy found (and this checkpoint fixed)

The attended deploy was not ceremony. `deploy/deploy.sh` step 4 issued an unconditional
`manage.py migrate` right after `docker compose up -d`, commented "normally a no-op,
because boot.sh already migrates on container start". REQ-002's own deploy carried no
migration, so that assumption had never been tested. REQ-003 carries
`0243_userpreference_use_readable_time`, and the two runs raced: boot.sh's migration took
the lock, the script's blocked behind it and then died with
`psycopg2.errors.DuplicateColumn`, aborting the deploy at step 4.

Nothing was broken by it — the image was running, the column was there, `0243` was recorded
applied and the site was serving — but the deploy *reported failure over a success*, which
is the worse of the two directions to be wrong in, and it would have done so on every future
deploy carrying a migration, including the one the System Tester runs for AC4.

Step 4 now waits for the container's own startup migration to settle (polling
`showmigrations --plan` for unapplied entries, up to two minutes), migrates explicitly only
if something is still pending, and prints the last three applied cookbook migrations so the
log keeps the visible, ordered migration record that REQ-002's AC4 sign-off reads. The
re-run went through all five steps clean.

What the live host now shows, checked from here rather than assumed:

- running `ghcr.io/dr-froehlich/recipes:sha-b00564cb0…`, `TANDOOR_VERSION`/`TANDOOR_REF` both
  that commit
- `cookbook_userpreference.use_readable_time` exists, and all 5 existing preferences
  backfilled to `true` — the default reached the real database
- the served bundle contains `useDurationDisplay-*.js`, `useReadableTime` in the store chunk
  and `Use_Readable_Time` in the Cosmetic-settings chunk

## What this checkpoint deliberately does not do

AC4 is graded in the System-Test phase, as the REQ's Notes argue: the formatter's real risk
is covered exhaustively by AC1, and what remains is a wiring observation with a human oracle
and no fixing loop. The deploy itself is the System Tester's entrypoint via the committed
`deploy/deploy.sh` from REQ-002.
