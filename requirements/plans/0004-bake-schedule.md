# Plan 0004 — REQ-004's develop checkpoint: back-chained bake schedule

> Authored 2026-08-12. A plan is a thinking document: how a chunk of work will be
> approached, the alternatives weighed, the sequence. It is not a contract (REQs are).

## Context

Advances [REQ-004](../REQ-004.md) — a baker states when a recipe must be finished and reads,
per step, when that step has to start. REQ-003 made durations readable (`72 h` instead of
`4320 min`); this answers the *when* that made unanswerable.

The REQ froze the hard thinking: back-chain over `Step.time` alone (Decision 1), zero-time
steps inherit the following start (2), the finish time lives only in the URL (3), a weekday +
time picker rather than a calendar (4), planner values honoured verbatim at any horizon (5),
weekday-relative rendering with a day offset past a week (6), sub-recipes flagged not
recursed (7), a fourth column in the times row (8), luxon locale formatting rather than seven
new translation keys (9), and no backend change at all (10).

Shape of the work: one pure module with four concerns, one composable, one dialog component,
a fourth column in two layouts of `RecipeView`, one optional prop on `StepView`, one optional
prop on `RecipeCard`, two planner call sites, three translation keys, one spec module, and
one manual-sign-off test harness for AC5.

## Approach

### The one fork this plan had to resolve

**Fork A — what is the formatter's reference?** Decision 6 and the Requirement section
disagree with each other. The Requirement's example reads `Sat 18:30 (−9 d)` *"once the step
starts more than six days before the finish"* — a reference of **the finish time**, which is
where the minus sign comes from. But `Today 18:30` and `Tomorrow 06:00` in the same sentence
only mean anything against **now**. AC2 only ever says "relative to a fixed reference", so
the pure function and all four unit ACs pass either way; the fork is purely which reference
the page wires in, and it is what the AC5 operator reads on screen.

Asked and answered in session: **reference = now**. Every string then answers one question —
"when, relative to right now" — `Today`/`Tomorrow` mean what they say, and a start that has
already passed renders with a *negative* offset, which is exactly the "you are too late for
this finish time" signal a baker needs. The cost is that the REQ's literal `(−9 d)` becomes
`(+9 d)` for a start nine days out; the negative form now means nine days *ago*.

Rejected: reference = the finish time. It preserves the REQ's literal phrasing at the price
of `Today` meaning "the finish day" on a page you are looking at three days earlier — the
one reading guaranteed to be misread.

### `vue3/src/utils/schedule_utils.ts` — one module, four concerns

Modelled on `duration_utils.ts`: pure, no app imports, labels passed in by the caller so no
UI string is inlined in the logic. Unlike `duration_utils` it does import luxon `DateTime`,
which is the point — DST-correct arithmetic is not something to hand-roll.

**Back-chain (AC1).** `backChainSchedule(finish, durations)` walks the duration list
backwards from the finish, returning `{overallStart, stepStarts}`:

```
next = finish
for i from last down to 0:
    next = next.minus({minutes: normalize(durations[i])})
    stepStarts[i] = next
```

`normalize` maps anything that is not a finite positive number — `0`, `null`, `undefined`,
`NaN`, negatives — to `0`, which makes Decision 2 fall out for free: a zero-duration step
subtracts nothing and therefore starts exactly when the step after it starts. An empty list
leaves `next` at the finish, so `overallStart` is the finish with no per-step offsets, as is
an all-zero list.

DST is luxon's to get right and it does: `minus({minutes: n})` is *absolute* time (only
`days`/`weeks`/`months` are calendar-aware). A 1440-minute step ending Sunday 12:00 CEST
after a spring-forward starts Saturday **11:00** CET, not 12:00 — 24 real hours of ferment
across a night that only had 23 wall-clock hours. That is the correct answer for a physical
process and it is what AC1's three-day DST chain pins down.

**Format (AC2).** `formatStartTime(start, reference, labels)`. The day offset is computed on
calendar days (`startOf('day')` on both sides), not on elapsed hours, so a 23-hour gap that
crosses midnight counts as one day:

| offset | render |
|---|---|
| `0` | `Today 18:30` |
| `1` | `Tomorrow 06:00` |
| `-6 … -2`, `2 … 6` | `Sat 18:30` |
| beyond ±6 | `Sat 18:30 (+9 d)` / `Sat 18:30 (-9 d)` |

Weekday comes from `toLocaleString({weekday: 'short'})` — Decision 9, the runtime already
localizes weekday names — and the clock from `toFormat('HH:mm')`. No branch can emit a
calendar date. Only `Today` and `Tomorrow` are labels, and they are passed in.

Two deliberate details. The bare-weekday band is symmetric (`±6`) because AC2 says "two to
six days away **in either direction**"; that does make `Fri` ambiguous across a 13-day
window in the already-late case, which is the price of following the AC literally rather
than special-casing the past. And the sign is ASCII `+`/`-`, not the REQ's typographic
`−` (U+2212) — it survives a terminal, a printout and a copy-paste unchanged, and it is what
the resolved Fork A preview used.

**Weekday resolution (AC3).** `nextOccurrence(weekday, hour, minute, reference)` sets the
reference to that ISO weekday and time, then adds whole weeks until it is strictly after the
reference. `set({weekday})` moves within the current Mon–Sun week, so the loop is what turns
"Monday, viewed on Sunday" into *next* Monday rather than six days ago — and it is also what
makes "today, but the time already passed" roll a week, as AC3 requires. `plus({weeks: 1})`
is calendar-aware, so the chosen wall-clock time survives a DST boundary.

**Query param (AC3).** `serializeFinishTime` / `parseFinishTime`. Serialized as **UTC ISO
with a `Z`** (`2026-08-23T10:00:00Z`) rather than a zoned ISO string, because a zoned ISO
carries a literal `+` in its offset — the one character a query string reads as a space if
anything anywhere mishandles the encoding. Parsing sets the result back to the local zone,
so the same instant comes back and the wall clock is right for the viewer. A missing,
non-string, empty or malformed value returns `undefined`; `DateTime.fromISO` returns an
*invalid* DateTime rather than throwing, so the guard is `.isValid`.

**Sub-recipe guard (AC4).** `findUnschedulableSteps(steps)` returns the steps that carry a
`stepRecipe` while their own duration normalizes to `0` — the exact case Decision 7 refuses
to let stay silent. Each hit carries its zero-based `index` and its `name`; composing the
"Step 3"-style fallback for an unnamed step is the caller's job, because that fallback is a
translated string. An empty array means the schedule is complete.

### `vue3/src/composables/useStartTimeDisplay.ts`

The `useDurationDisplay` pattern exactly: binds the pure formatter to the active locale and
the `Today`/`Tomorrow` keys, and supplies `DateTime.now()` as the reference so no caller has
to remember to. Returns `(start: DateTime) => string`.

### `vue3/src/components/dialogs/BakeScheduleDialog.vue`

Mirrors `RecipeScalingDialog` — `activator="parent"`, so hanging it inside the times column
gives it the whole column as its hit area in both layouts (Decision 8). A weekday `v-select`
plus the house time control (a readonly `v-text-field` opening a `v-time-picker` in a
`v-menu`, copied from `MealPlanEditor`'s meal time field). Actions are `Clear` and `Save`;
`Save` emits `confirm` with the resolved next occurrence, `Clear` emits `clear`.

Opening with a finish already set seeds the picker from it — including a planner value three
weeks out, whose weekday and time show correctly even though the picker cannot itself
express that horizon. Touching Save re-snaps to the next occurrence, which is Decision 5's
stated behaviour, not an accident.

### The call sites

`RecipeViewPage` owns the URL, exactly as it already owns `servings`: a computed `finish`
reading `params.finish` through `parseFinishTime`, and a setter writing the serialized form
or `delete`-ing the key. `delete` on the `useUrlSearchParams('history')` reactive is safe —
its write watcher rebuilds the query from `Object.keys(state)` each time, so a deleted key
leaves the URL entirely, which is what AC5 (c) checks.

`RecipeView` takes `finish` as a prop and emits `update:finish`, computes the schedule once
in a `computed`, and renders:

- a fourth `v-col` in **both** times rows — unset it offers to set a finish, set it shows the
  overall start;
- `:start-time` on each `step-view`, pre-formatted;
- a `v-alert` naming the offending steps when the guard fires.

`StepView` takes `startTime?: string` — a *string*, not a DateTime, which is what keeps the
component dumb and, more importantly, makes the no-recursion rule structural: the recursive
`step-view` call for a sub-recipe's steps simply does not pass the prop, so a sub-recipe step
cannot render a start time even by accident. The span sits beside the timer button group but
outside it, because that group is `d-print-none` and start times must print.

The guard alert renders only when a finish time is set. With no finish there are no start
times on the page, so there is nothing that could be misread as authoritative — which is the
whole stated purpose of Decision 7 — and an unconditional warning would nag on every visit to
a recipe nobody is scheduling.

**Planner hand-off.** `HorizontalMealPlanWindow.clickMealPlan` adds `finish` to the query it
already builds for `servings`. `RecipeCard` gains an optional `finish?: Date` prop folded
into its `dest` computed next to `servings`, and `MealPlanEditor` passes
`editingObj.fromDate` to the embedded card. Both entry points then carry the planned meal's
datetime verbatim, at any horizon (Decision 5).

### Translations

Three new keys in `en.json` only, per Decision 9 and CLAUDE.md's rule against hand-editing
Weblate-managed catalogs: `Tomorrow`, `FinishTime`, `ScheduleIncomplete`. `Today`, `Start`,
`Clear`, `Save`, `Time` and `Finish` already exist and are reused.

## Build sequence

1. `schedule_utils.ts` + `schedule_utils.spec.ts` — AC1–AC4 green before any component exists.
2. `useStartTimeDisplay.ts`.
3. `BakeScheduleDialog.vue`.
4. `RecipeViewPage` param plumbing → `RecipeView` column, alert and step wiring → `StepView` prop.
5. Planner hand-off: `RecipeCard` prop, `MealPlanEditor`, `HorizontalMealPlanWindow`.
6. Translation keys.
7. AC5's sign-off harness — the graded-from-evidence test the System Tester's capture feeds.

## Verification

AC1–AC4 are `regression`, all four on `yarn --cwd vue3 test`, all four against synthetic
tables: there is no production corpus that can surprise a pure function of a datetime and a
list of integers.

AC5 is `manual` and belongs to the System-Test phase, because what it checks is *wiring* —
that the column reaches both `RecipeView` layouts in a built bundle, that clearing really
clears, and that the planner hand-off survives the round trip through a query param. The
harness recomputes the expected chain from the step durations the tester records, so a
recipe whose times are edited later is still graded correctly. Per REQ-030 the green develop
gate therefore commits without landing; the flip waits for `steward validate REQ-004`.

## What this checkpoint deliberately does not do

No model, migration, serializer or API change, and therefore no OpenAPI client regeneration
(Decision 10) — which also keeps this clear of the enterprise/open-data plugin trap Plan 0003
documented. No recursion into `step_recipe` step lists: flagged, homed in a follow-on REQ.
Nothing is written back to the meal plan. No start times on the meal plan calendar or in
share-link views. `Timer.vue` is untouched, and duration *entry* stays in minutes.
