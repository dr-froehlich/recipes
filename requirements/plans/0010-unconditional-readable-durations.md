# Plan 0010 — REQ-010's develop checkpoint: unconditional readable durations

> Authored 2026-09-07. A plan is a thinking document: how a chunk of work will be
> approached, the alternatives weighed, the sequence. It is not a contract (REQs are).

## Context

Advances [REQ-010](../REQ-010.md). The maintainer accepted REQ-003's feature and declined
its mechanism, so one thing is deleted from two trees: `UserPreference.use_readable_time`.
The fork loses it first, then a fresh branch carries the unconditional formatter to a new
pull request.

`develop: fused` — no design review. The shape is dictated by a maintainer's explicit
instruction, and REQ-005 already ran the publication mechanics once.

## What the environment says today

Measured at the start of this session, after `git fetch upstream`:

| Fact | Value | Consequence |
|---|---|---|
| merge base with `upstream/develop` | `9f6d43b95` | unchanged since REQ-005 |
| upstream commits we lack | **129** | up from 10 at REQ-005; every file the branch touches has to be re-checked, not trusted from plan 0005 |
| our local commits | 63 | all fork harness plus REQ-002…REQ-009 |
| `RecipeCard.vue`, `StepView.vue` upstream | **0** commits since the merge base | REQ-003's edits apply exactly |
| `RecipeView.vue` upstream | 1 commit (`a4b176b9f`, "added new model select almost everywhere") | the four duration lines are byte-identical to REQ-003's Context table; the commit touched other parts of the file |
| `en.json` upstream | 2 commits; has `min`, `Hour`, `Hours`, **no `h`** | the PR still adds exactly one key |
| `package.json` upstream | 3 commits | apply our delta by hand, never whole-file checkout |
| `yarn.lock` upstream | 18 commits | **regenerate** on the branch, as plan 0005 did |
| migrations upstream | tops out at `0242` | nothing to renumber — the branch adds no migration at all |
| toolchain | java, openapi-generator-cli, yarn 1.22.22, node v22.22.1, `gh` as `dr-froehlich` | everything this REQ needs is present |

## The one genuinely awkward part: the generated client

CLAUDE.md's rule is that `vue3/src/openapi/` is generated and must never be hand-edited, and
its trap is that regenerating in this checkout — which lacks the enterprise and open-data
plugins the committed client was generated with — deletes ~40 model files and two thirds of
`ApiApi.ts`. Plan 0003 paid that cost once and restored around it.

**There is a better move here, and it is exact rather than careful.** Both generated model
files were last touched by `b00564cb0` (REQ-003's own commit), and upstream has not touched
either since the merge base. `git diff b00564cb0^ HEAD` on them is *precisely* the six
`useReadableTime` hunks — the interface property, the `FromJSONTyped` read, and the
`ToJSONTyped` write, in each of the two files, and nothing else. So restoring
`b00564cb0^` for exactly those two paths **is** what the generator would emit for a
serializer without the field. No dev server, no Java, no plugin stripping, and the result is
verifiable by diffing rather than by trusting a regeneration to have behaved.

This is not hand-editing a generated file. It is restoring a generated file to the
generator's own prior output, which is the thing the rule exists to protect.

## Sequence

### 1. The fork loses the preference

| File | Change |
|---|---|
| `cookbook/models.py:531` | delete the `use_readable_time` field |
| `cookbook/serializer.py:581` | drop it from `UserPreferenceSerializer.Meta.fields` |
| `cookbook/migrations/0245_remove_userpreference_use_readable_time.py` | new, `RemoveField`, depends on `0244_step_working_time` |
| `vue3/src/utils/duration_utils.ts` | drop the `useReadableTime` parameter and the `!useReadableTime` branch |
| `vue3/src/composables/useDurationDisplay.ts` | stop reading `UserPreferenceStore`; keep the i18n label binding |
| `vue3/src/utils/duration_utils.spec.ts` | drop every preference-off case; keep the format table |
| `vue3/src/components/settings/CosmeticSettings.vue:34` | delete the checkbox |
| `vue3/src/locales/en.json` | delete `Use_Readable_Time`, `Use_Readable_Time_Help`; keep `h` |
| `vue3/src/openapi/models/{UserPreference,PatchedUserPreference}.ts` | restore from `b00564cb0^` |
| `cookbook/tests/api/test_api_user_preference.py` | delete |
| `cookbook/tests/other/test_openapi_client_fresh.py` | delete |
| `cookbook/tests/other/test_readable_time_signoff.py` | delete |

The six display call sites are **not** touched: they call `displayDuration(...)`, which keeps
its signature. That is the payoff of REQ-003 Decision 5 — the preference was read in exactly
one place.

### 2. The gate's own tests

- `cookbook/tests/other/test_readable_time_unconditional.py::test_preference_is_gone` — AC1.
  Asserts across all seven layers at once (model, serializer, migration state, `en.json`,
  `CosmeticSettings.vue`, both generated client models, `duration_utils.ts`). Coupled oracle,
  self-contained against a clean checkout.
- the rewritten `duration_utils.spec.ts` — AC2. Adds the teeth the REQ names: **no argument
  or code path restores raw minutes**, checked by calling `formatDuration` with a stray extra
  argument and asserting the readable form comes back anyway.
- `cookbook/tests/other/test_upstream_pr_v2_branch.py` — AC3 and AC4. Modelled on
  REQ-005's module, with the manifest inverted: the strong assertion is now that the branch
  touches **no `cookbook/` path at all**, plus no `vue3/src/openapi/`, no migration, and no
  occurrence of the string `use_readable_time` anywhere in the diff.
- `cookbook/tests/other/test_unconditional_time_signoff.py` — AC5's grader, evidence-driven,
  recomputing the expected strings from the durations the tester records.
- `cookbook/tests/other/test_upstream_pr_v2_signoff.py` — AC6's grader.

### 3. Deploy and read the instance

A develop obligation, not a validation step (REQ-010 Notes). `deploy/deploy.sh` from
REQ-002, then read the Cosmetic settings page and a recipe against AC5's PASS list, and fix
in place whatever it turns up. The System Tester will capture the same surfaces formally
later; the point of doing it here is that a wiring mistake gets a repair loop.

### 4. The branch

`readable-durations-v2`, cut from `upstream/develop` at its fetched tip.

**Commit 1 — the formatter.** `duration_utils.ts` and `useDurationDisplay.ts` in their
post-simplification fork shape (whole-file copy is safe: upstream has neither file). The `h`
key added to upstream's `en.json` by hand. `RecipeView.vue`, `RecipeCard.vue` and
`StepView.vue` edited **on upstream's versions**, not copied from the fork — `StepView.vue`
especially, whose fork version carries REQ-008's per-step working/waiting rows that do not
exist upstream. Four call sites, one import each.

**Commit 2 — vitest.** `vitest.config.ts` and the spec whole-file from the fork;
`package.json` delta applied by hand onto upstream's; `yarn.lock` regenerated by running
`yarn install` on the branch.

Then, on the branch: `yarn test`, `yarn build`, prettier on every changed `.vue`/`.ts`, and
push to `origin` so the fork's own workflows run before anything is published.

### 5. Publication

`gh pr create` from `dr-froehlich/recipes:readable-durations-v2` to
`TandoorRecipes/recipes:develop`; a comment on #4785 answering the review; a comment on #382
pointing at the new PR. Description sanitized of fork vocabulary, referencing both issues,
stating the behaviour is unconditional, and **not** offering to drop the vitest commit
(REQ-010 Decision 6).

## Alternatives weighed

**Regenerate the client properly rather than restoring two files.** Rejected above: it is
strictly more destructive and strictly less verifiable for a change that removes one boolean.

**Keep `useDurationDisplay` inline at the call sites now that it only binds labels.** Rejected.
It is three lines that stop four components from each reaching for `useI18n` and spelling the
label object themselves, and collapsing it would enlarge the PR's diff for no gain.

**Cherry-pick the fork's `StepView.vue` onto the branch.** Rejected — it carries REQ-008.
This is the one file where the two trees genuinely diverge, and the branch takes upstream's.

**Delete `h` from the fork too, since upstream may never merge it.** Not considered seriously:
the key is load-bearing in this fork's own display path.
