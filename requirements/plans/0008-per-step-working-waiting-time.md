# Plan 0008 — REQ-008's develop checkpoint: per-step working and waiting time

> Authored 2026-08-16. A plan is a thinking document: how a chunk of work will be
> approached, the alternatives weighed, the sequence. It is not a contract (REQs are).

## Context

Advances [REQ-008](../REQ-008.md) — a step records how much of its duration the cook is
actually present for, and a recipe's working/waiting totals stop being an independent claim
and become the sum of its steps.

The REQ froze the hard thinking: `Step.time` keeps meaning total elapsed and gains
`Step.working_time` as the attended portion inside it (Decision 1), work comes first within
a step (2), `working_time ≤ time` (3), recipe totals are materialized into the columns rather
than computed on read (4), recipe times stay hand-editable only while the steps total 0
elapsed (5), the lock rejects on the two paths a person types into but accepts-and-overwrites
on create and import/export (6), the editor shows Working and Waiting and stores
`time = working + waiting` (7), the conversion lives in a plain TS module (8), no recursion
into sub-recipes (9), the backfill is proven live in this session (10), REQ-004 untouched (11).

This is the fork's **first model change**. Shape of the work: one field, one migration with a
backfill, one helper module, three signal receivers, four serializer touches, one view change,
one regenerated API client, one pure TS module, four frontend components, one new translation
key, three pytest modules, one vitest spec, one sign-off harness.

## Approach

### The forks this plan had to resolve

**Fork A — does the lock reject on *presence* or on *change*?** The REQ says
`RecipeSerializer` "rejects an update that sets `working_time` or `waiting_time`". Read
literally as *presence*, that breaks the fork's own recipe editor: `ModelEditPage` PATCHes the
whole recipe object, so a derived recipe's editor would submit the derived values back and be
rejected on every save — including saves that only changed the title. Any external client doing
a full `PUT` would break the same way.

Resolved as **reject on change**: an update is rejected when the submitted `working_time` or
`waiting_time` *differs* from what the steps derive. Resubmitting the derived value is a no-op
and passes. This is the lock the REQ intends — you cannot type a number that contradicts the
steps — without an idempotency trap that no requirement asked for. AC2 is satisfied as written
(a PATCH setting a different value is rejected); the test covers both branches so the
no-op-tolerance is itself pinned.

**Fork B — where does step deletion get its recipes?** `post_delete` on `Step` is too late:
Django's collector cascades the `Recipe.steps` through-rows before deleting the step, so
`instance.recipe_set` is already empty by then. `m2m_changed` does not fire for cascaded
through-row deletes either, so it cannot stand in.

Resolved by the pattern already in `signals.py` for `UserSpace` (`pre_save` stashes, `post_save`
acts): **`pre_delete` stashes the owning recipe ids on the instance, `post_delete` recomputes
them**. drf-writable-nested removes dropped steps with a queryset `.delete()`, which still sends
per-object signals, so nested recipe writes are covered by the same path.

**Fork C — does the backfill make things worse before it makes them better?** Yes, and the REQ
says so. Every existing step has `working_time` 0, so a recipe with timed steps materializes to
working 0 / waiting = elapsed. The household's Pizza recipe goes from a curated 45/2400 to
0/1440, and the 2400 is gone rather than shadowed. Decision 10 and the REQ's "Accepted data
loss" note own this. What the plan adds is the mitigation: **the develop session records every
affected recipe's pre-migration values before the migration runs on the deployment**, so the
household can restore or re-time deliberately rather than discover the change.

### Backend

**`Step.working_time`** — `IntegerField(default=0, blank=True)`, placed directly after `time`
so the pair reads together. `blank=True` matches `time`.

**`cookbook/helper/recipe_time_helper.py`** — one module, three functions, no imports from
views or serializers so every layer can use it:

```
step_time_totals(recipe)     -> (elapsed, working, waiting)   one aggregate query
recipe_times_are_derived(r)  -> elapsed > 0
recalculate_recipe_times(r)  -> bool   writes the columns when derived, returns whether it did
```

`recalculate_recipe_times` writes with `Recipe.objects.filter(pk=...).update(...)` rather than
`instance.save()`. Two reasons: `.update()` does not fire `post_save` on `Recipe`, so it cannot
re-enter the search-vector receiver, and it cannot clobber a concurrent write to an unrelated
field the way a full `save()` of a stale instance would. The write is skipped entirely when the
values already match, so a step save that changes only an instruction costs one `SELECT`.

**Signals** (`cookbook/signals.py`, beside the existing `Step` receiver):

| Signal | Sender | Does |
|---|---|---|
| `post_save` | `Step` | recompute every recipe in `instance.recipe_set` |
| `pre_delete` | `Step` | stash `instance._time_recipe_ids` |
| `post_delete` | `Step` | recompute the stashed ids |
| `m2m_changed` | `Recipe.steps.through` | recompute on `post_add` / `post_remove` / `post_clear` |

All decorated with the file's existing `@skip_signal` where they hang off `post_save`, so the
search-vector receiver's inner `instance.save()` does not trigger a second recompute. All
wrapped in `scopes_disabled()` — signals fire from management commands and migrations as well
as requests, and `Recipe.objects` is a `ScopedManager`.

**Serializers:**

- `StepSerializer` — `working_time` into `Meta.fields`; `validate()` raises when
  `working_time > time`, resolving both values against `self.instance` so a PATCH that sets only
  one of them is still checked against the other's stored value.
- `StepExportSerializer` — `working_time` into `Meta.fields`, so a Tandoor export round trip
  carries the split. This is what makes Decision 6's accept-and-overwrite necessary rather than
  theoretical.
- `RecipeSerializer.validate()` — Fork A's change-based lock, on update only (`self.instance`
  present). Create is untouched.
- `Step.clean()` — the same `working_time ≤ time` rule at the model, for the Django admin and
  for anything calling `full_clean()`. No `CheckConstraint`: an `IntegrityError` surfacing out
  of an importer would be a worse failure mode than a `ValidationError`, and every existing row
  is compliant by construction anyway.

**`api.py` batch update** — the current `recipes.update(working_time=...)` bypasses every save
hook by design, so it has to learn the lock itself. Replaced with a variant that narrows to the
recipes whose steps total 0 before updating; derived recipes are silently left alone, which is
what the REQ's "rejects or skips" allows and the only behaviour that makes sense for a bulk
action over a mixed selection.

**Migration `0244_step_working_time`** — `AddField`, then a `RunPython` backfill that calls the
same `recalculate_recipe_times` the signals use, under `scopes_disabled()`, across every recipe
in every space. Reverse is `RemoveField` plus a no-op: the derived totals cannot be un-derived
because the values they replaced are not recorded anywhere. That asymmetry is stated in the
migration's docstring rather than hidden.

### Frontend

**`vue3/src/utils/step_time_utils.ts`** — the pure module AC4 grades, modelled on
`duration_utils.ts`: no app imports, no i18n, total functions.

```
toStoredStepTime(working, waiting) -> {time, workingTime}
fromStoredStepTime(time, workingTime) -> {working, waiting}
```

`normalize` maps anything not a finite positive number to 0, exactly as `schedule_utils.ts`
does, so `null`/`undefined`/`NaN`/negatives cannot produce a negative waiting value.
`fromStoredStepTime` additionally clamps `workingTime` into `[0, time]`, which makes the round
trip total for any input pair and means a row that somehow violated the model constraint
displays as something rather than as nonsense.

**`StepEditor.vue`** — the single Time input becomes two, Working and Waiting, reusing the
existing `WorkingTime` / `WaitingTime` keys. Bound through a computed pair that reads
`fromStoredStepTime(step.time, step.workingTime)` and writes back via `toStoredStepTime`, so
the component holds no arithmetic. The overflow menu's "Time" entry reveals both and its
`step.time == 0` condition is unchanged.

**`StepView.vue`** — where one duration is shown today, show working and waiting when both are
non-zero and a single value when only one is, all through the existing `useDurationDisplay()`
so REQ-003's readable rendering applies. The stopwatch button and `Timer` keep counting
`step.time`: it still means elapsed, which is what a step timer should run for.

**`RecipeEditor.vue`** — the Working/Waiting inputs get `:disabled` off a computed over
`editingObj.steps`, with a hint line explaining why. One new English key, `TimesDerivedFromSteps`.

**`BatchEditRecipeDialog.vue`** — the dialog cannot know the selection's step times, so it
states that recipes with step times are skipped, reusing the same key.

**`RecipeView.vue`** — untouched. It already renders `recipe.workingTime` / `waitingTime`, which
are now the derived values.

**API client** — `Step.ts`, `PatchedStep.ts` (and whatever else the generator touches) must be
regenerated per CLAUDE.md: run the dev server, `PYTHONPATH=$(pwd) python scripts/generate_api_client.py`,
then `git checkout -- vue3/src/openapi` and restore only the files this change actually needs.
The ~40 plugin model files and two thirds of `ApiApi.ts` must come back untouched — that is the
documented trap and the one step of this plan that is verified by diffing, not by a test.

### Tests

| AC | Module | Grades |
|---|---|---|
| AC1 | `cookbook/tests/other/test_recipe_time_derivation.py` | materialization on save / delete / nested write / m2m change, the all-zero no-op, two-recipe steps, sub-recipe non-recursion, the backfill mechanism |
| AC2 | `cookbook/tests/api/test_api_recipe_time_lock.py` | PATCH rejected on change and accepted on no-op, batch endpoint skip, unlocked recipe still editable, create-with-steps, export round trip |
| AC3 | `cookbook/tests/other/test_step_working_time.py` | `working_time ≤ time` at endpoint / nested / model, defaults, serializer round trip |
| AC4 | `vue3/src/utils/step_time_utils.spec.ts` | the conversion round trip and its clamping |
| AC5 | `cookbook/tests/other/test_step_time_signoff.py` | evidence harness, recomputing expectations from the tester's recorded step values |

The API tests follow `cookbook/tests/api/`'s per-endpoint pattern (`register(Factory, …)`,
`LIST_URL`/`DETAIL_URL`, the `a_u`/`u1_s1`/… client fixtures). The derivation tests need direct
ORM access, so they live in `tests/other/` under `scopes_disabled()` per `conftest.py`.

## Sequence

1. Model field + `clean()`, helper module, signals — the mechanism, with AC1 and AC3 green first.
2. Serializers + the batch view + AC2.
3. Migration with the backfill, and AC1's backfill case.
4. Regenerate the API client and restore the plugin files.
5. Pure TS module + AC4, then the four components.
6. AC5's harness.
7. `yarn build`, deploy, capture the pre-migration values, run the backfill live, inspect
   (Decision 10). Iterate here — this is the attended grant, and it is why the proof is not
   deferred to the System Tester.
8. `steward checkpoint REQ-008 develop`. AC5 is `manual`, so the land defers: the close commits
   the work and the flip waits for `steward validate REQ-008`.

## Appendix — pre-migration state of the household collection (captured 2026-08-16)

Decision 10's live proof, read-only, before any deploy. Exactly **three** recipes in the whole
collection have steps carrying elapsed time and are therefore affected; every other recipe keeps
hand-edited totals and is untouched.

| id | recipe | curated work / wait | step elapsed | after migration |
|---|---|---|---|---|
| 234 | Baguette | 0 / 0 | 725 | 0 / 725 |
| 2 | Kartoffelsalat | 50 / 600 | 190 | 0 / 190 |
| 1 | Pizza | 45 / 2400 | 2450 | 0 / 2450 |

Per-step times as captured:

- **Baguette** — `Gehzeit` 720, `Poolish (Vorteig)` 5, thirteen further steps at 0.
- **Kartoffelsalat** — `Kartoffeln kochen` 5, `Kochzeit` 20, `Kartoffeln schälen` 10,
  `Zwiebeln` 5, `Dressing` 15, `Salat schichten` 10, `Salat zwei Stunden ziehen lassen` 120,
  `Öl zugeben und mischen` 5; the two day-header steps at 0.
- **Pizza** — `Tag 1: Vorteig` 10, `Teig über Nacht gehen lassen` 720, `Tag 2: Hauptteig` 5,
  `Mischen` 5, `Kneten` 10, `Stockgare im Kühlschrank` 1440, `Tag 3: Pizzaballen formen` 10,
  `Stückgare` 240, `Belegen` 5, `Backen` 5.

**The premise of REQ-008 is confirmed by this data.** Summing only the steps that are plainly
attended gives 10 + 5 + 5 + 10 + 10 + 5 = **45** for Pizza and 5 + 10 + 5 + 15 + 10 + 5 = **50**
for Kartoffelsalat — exactly the curated `working_time` of each. The household already authored
its step times as a working/waiting split; the model simply had nowhere to record which was
which. Pizza's waiting steps likewise sum to 720 + 1440 + 240 = **2400**, exactly its curated
`waiting_time`.

**What the migration costs, precisely:**

- **Baguette** is a strict improvement: it shows no time at all today and will show 12 h 5 min.
- **Pizza** keeps its total (2450 against a curated 2445 — the 5-minute `Backen` step was in
  neither curated figure) but loses the 45/2400 split until six named steps get a working time.
  Fully recoverable, and the step names say exactly which six.
- **Kartoffelsalat** is the one real regression: 650 minutes total becomes 190. Its curated
  waiting time of 600 includes the overnight rest between `Tag 1` and `Tag 2`, which lives in
  **no step at all** — 460 minutes that the step list never recorded. This is a genuine modelling
  gap that the new model can express (put the wait on the `Tag 1` step) but that no migration
  can infer.

### Post-deploy verification (2026-08-16, commit 099c2a0bb)

Deployed with `deploy/deploy.sh --yes`; migration `0244_step_working_time` applied; verified
restorable dump taken first at `deploy/dumps/tandoor-20260816T113100Z.dump`. The backfill did
exactly what the table above predicted, with no surprises:

| recipe | after migration | step elapsed / working |
|---|---|---|
| Baguette | 0 / 725 | 725 / 0 |
| Kartoffelsalat | 0 / 190 | 190 / 0 |
| Pizza | 0 / 2450 | 2450 / 0 |

Across the whole collection of **273 recipes**: 3 derived, 1 with hand-edited totals and no step
times (preserved untouched), 269 with no times at all (untouched). The migration touched nothing
it was not meant to touch, which is the property that mattered — the recipe-level fields stay
hand-editable for every recipe any importer has ever produced.

Remaining household follow-up, not code: set working times on Pizza's six attended steps (10, 5,
5, 10, 10, 5) and Kartoffelsalat's six (5, 10, 5, 15, 10, 5) to restore the splits, and put
Kartoffelsalat's overnight rest on its `Tag 1` step to recover the 460 minutes that live in no
step.

## Risks

- **The OpenAPI regeneration** is the one irreversible-looking step. Mitigated by doing it on a
  clean tree with everything else committed, so `git checkout -- vue3/src/openapi` is always
  available as a full undo.
- **The backfill is lossy by design** (Fork C). Mitigated by capturing pre-migration values, not
  by changing the behaviour — the household chose it.
- **Signal recursion.** The recompute writes with `.update()`, which fires no `post_save`, and the
  receivers carry `@skip_signal`. Both belts are deliberate.
- **`working_time` on a step with `time` 0.** Unreachable through the editor (Fork/Decision 7)
  and rejected by validation, but the display clamps anyway rather than trusting the constraint.
