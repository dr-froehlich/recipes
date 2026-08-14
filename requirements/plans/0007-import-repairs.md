# Plan 0007 — REQ-007's develop checkpoint: repairing the imported ingredient lines

> Authored 2026-08-14. A plan is a thinking document: how a chunk of work will be
> approached, the alternatives weighed, the sequence. It is not a contract (REQs are).

## Context

Advances [REQ-007](../REQ-007.md). REQ-006 put the household's 270 recipes into Tandoor with
their structure intact and the *inside* of their ingredient lines wrong: `IngredientParser`
takes the token after the amount as the unit, and in German that token is usually an
adjective. `1 reife Avocado` arrived as one *reife* of *Avocado*; `1 Eigelb zum Bestreichen`
arrived as a row containing no egg yolk at all.

The REQ froze the hard thinking: the repair lives in the Word importer rather than the shared
parser (Decision 1), one rule plus closed lists rather than a per-word repair table (2), the
repair runs after parsing (3) except for two fixes that change tokenisation (4), the lists live
in one committed file rather than Automation rows (5), a grade keeps its number and loses its
German suffix (6), a keep-whole list overrides the rule for genuine multi-word names (7), a
repair that would make a line worse is not applied (8), the existing data is fixed by restoring
the pre-import dump and re-importing (9), the list is produced by running the corpus (10), only
the Word importer is affected (11), and the ten table-shaped Chefkoch documents are declined
permanently (12).

The rule, in one line: **the food is the thing you buy — the last capitalised noun; everything
that qualifies it becomes a note.** German does the work, because attributive adjectives are
lowercase and nouns are capitalised.

## Shape of the work

One new pure module (`cookbook/integration/word_repairs.py`), a six-line change in
`cookbook/integration/word.py`, two new fixture documents with their generator, one test module
carrying AC1–AC6, one manual-sign-off harness for AC7, and the corpus run and live re-import
that Decisions 9 and 10 make obligations of this session.

`word_repairs.py` is pure the way `word_parser.py` is pure — no Django, no models, no request —
so the rule can be run over a folder of documents standalone. That is not decoration: the whole
of this session's calibration was a loop over the 342 real documents with nothing but this
module and the parser in it.

Two entry points, which is exactly Decisions 3 and 4:

```python
prepare_line(line)                        -> [line] or [line, line]   # before parsing
repair(line, amount, unit, food, note)    -> (amount, unit, food, note)   # after parsing
```

`repair` takes the line as well as the parse because of one case the parsed values cannot show
on their own: `1050er Weizenmehl` reaches it as *1050* of unit *er*, and only the line says the
amount and the unit came out of a single word.

## The lists, and what the corpus made of them

Measured over the curated collection — 270 documents, **2639 raw ingredient lines**, the same
set REQ-006 imported:

| | before | after |
|---|---|---|
| distinct foods | 782 | **500** |
| distinct units | 98 | **33** |
| units that are not a kitchen unit | 65 | **0** |
| foods used exactly once | 526 | 278 |
| flour foods (`…mehl`) | 18 | **5** |

The 33 surviving units are all genuine (`g`, `El`, `ml`, `Tl`, `Bund`, `Prise`, `kg`, `l`,
`Becher`, `Dose`, …); the 65 that went are the 30 adjectives, the 7 range fragments and the
nouns that were never units at all. The nine flour foods (`Weizenmehl`, `1050er Weizenmehl`,
`550er Weizenmehl`, `405er Weizenmehl`, `Weizenmehl Typ 550`, and the Roggen/Dinkel
equivalents) are now three, with the grade in the note; the other two `…mehl` foods are
`Mehl` itself and `Weizenvollkornmehl`.

Six sections of data, and they stayed small, which is the whole claim of Decision 2:

- **cut prepositions** (26 words) — where a note begins. `Butter für die Form`,
  `Thunfisch in Öl`, `Weizenmehl Typ 550`.
- **cut conjunctions** (4) — `oder`, `und`, split off from the prepositions because they only
  open a note *after* the food has been named (below).
- **drop words** (27) — articles and filler: `Etwas Zitronensaft`, `Verschiedene Kräuter`.
- **known units** (58 aliases → 35 spellings) — including the spelled-out `Teelöffel`/
  `Esslöffel` and the plurals, so `EL`, `El` and `Esslöffel` meet as one Unit.
- **unit conversions** (1) — `Tasse` → 180 ml, ruled.
- **keep-whole** (6) and **food aliases** (13) — the multi-word names the rule must not split,
  and the plurals `get_food` would otherwise keep as separate rows.
- **de-inflection irregulars** (23 forms of 5 adjectives) — a seventh section the corpus forced:
  German drops the stem's own `e` before an ending, so the general rule leaves `saure` as
  *saur*. Five adjectives need naming; every other adjective in the collection de-inflects by
  rule, which is why there is no adjective list.

`Crème fraîche` needs no entry, exactly as Decision 7 predicted — the rule leaves it alone
because its second word is lowercase.

## Reconciling with the owner's rulings file

`REQ-007-rulings.yaml` at the repository root is the owner's own data, written at intake. Its
lists are the starting point for the six sections above, and everything in it is honoured except
where the corpus showed the entry fighting a ruling elsewhere in the same file. Both exceptions
were put to the owner on 2026-08-14 and ruled:

| rulings file | what the corpus showed | ruled |
|---|---|---|
| `von` is a cut word | it keeps `Saft`, `Schale` and `Mark` as foods for 13 rows, against the file's own `Saft einer Limette → Limette · Saft` | **`von` stays out**, `vom` stays in |
| `Weizenmehl Typ 550` is keep-whole, *and* `typ` is a cut word | keeping it whole leaves a fourth flour food, which AC7 clause (b) grades against | **cut at `Typ`**, and the note reads `550` rather than `Typ 550` — "the former is preferred" |

Everything else the file names is in: `als` and `type` among the cut words, `verschiedenes`
among the drop words, `mg`/`dl`/`cm`/`Portion`/`Streifen` among the units, `hohe → hoch` among
the de-inflection irregulars. Where the file lists two spellings of one unit as separate units
(`Msp` beside `Messerspitze`, `Scheiben` beside `Scheibe`), they are folded into one, which is
the same move the REQ's own `Dosen → Dose` makes.

## Three places the rule needed more than the REQ spelled out

All three were found by running the corpus, and all three are the difference between a rule and
a list.

**A conjunction is not a cut word.** `Sonnenblumenöl oder Butterschmalz` is a choice between two
foods and the first one is the food; `frische oder getrocknete Petersilie` is a choice between
two adjectives and the food is still ahead. The test is what stands on either side of it: cut
only when a capitalised token precedes it and the token after it is not lowercase. That also
keeps `Rispen- oder Cocktailtomaten` whole, where the word in front is an elided compound
rather than a noun.

**`von` is not a cut word, though the REQ lists it as one.** It is the one preposition this
collection uses to say what a thing was made *from* — `Saft von 1 Zitrone`, `Schale von ½
Zitrone`, `Mark von 1 Vanilleschote` — and the owner's own ruling (`Saft einer Limette` →
`Limette` · *Saft*) says the fruit is the food there. Cutting at it would keep `Saft` as a food
for 13 rows and contradict the ruling for the spelling right next to it. `vom` stays a cut word:
`Brötchen vom Vortag` is bread, not a day.

**The phrase has to be put back in the order it was written.** `IngredientParser` moves an
amount it finds late in a line to the front, so `Saft von 1 Zitrone` reaches the rule as
`1 Zitrone Saft von` and the last capitalised token is no longer the noun the line ends on.
Reordering the phrase by where each token stands in the original line is a no-op for every line
the parser did not shuffle, and it is what turns REQ-007's third known residual (`Mark von 1
Vanilleschote` → `Mark`) into `Vanilleschote`.

## Not making a line worse (Decision 8)

Three guards, each of which the prototype earned:

- **A food phrase carrying a bracket is left alone.** The parser's own note handling is in play
  there, and re-cutting the phrase is precisely what turned `5–6 säuerliche Äpfel (z.B.
  Braeburn)` into the food `Braeburn)`.
- **The en-dash fix does not run on a line that has a parenthetical.** The parser rewrites a
  range by moving it to the end of the line, where it lands behind the existing parenthetical
  and the food phrase swallows the brackets — `4–6 Paprika (rot, gelb, grün)` would become the
  food `Paprika (rot, gelb, grün)`. Left alone, the range surfaces as a bogus unit instead,
  which the unit repair turns into a note without touching the food.
- **A repair that would empty the food, or that finds no capitalised noun to keep, is not
  applied.** `Zum Bestreichen`, `Für den Belag` and the other bulleted sub-headings come out
  exactly as the parser left them.

Verified over the whole collection: of the 2640 rows, the only ones whose food changed from a
food the parser had already resolved cleanly are the two keep-whole recoveries (`Bete` →
`Rote Bete`, `Würstchen` → `Wiener Würstchen`) and `Saft 1 Zitronen` → `Zitrone`. No food gained
a bracket. No food contains a comma. The only amounts that changed are the six `Tasse`
conversions.

## The fork this session had to put to the owner

**AC3 and AC5 contradict each other on one detail.** AC3 says `200 g Weizenmehl (550er)` yields
the food `Weizenmehl` *with the grade as a bare number*; AC5 says that for a plain
`375 g Weizenmehl (550er)` — a line the parser already handles correctly — the repaired result
must equal the unrepaired result **exactly**, and the parser writes that note as `550er`. Same
line shape, two incompatible demands.

Put to the owner on 2026-08-14 with both consequences spelled out. **Ruling: grades read as a
bare number wherever they end up, notes the parser itself wrote included** — the collection
spells the same flour `1050er Weizenmehl` and `Weizenmehl (550er)`, and the two forms should
read alike once they meet as one food. So:

- `GRADE_IN_NOTE` runs over the finished note. This is the one place a repair rewrites something
  the parser already had right, and it is deliberate.
- AC5's committed unchanged-set uses a plain `375 g Weizenmehl` in place of the REQ's
  `375 g Weizenmehl (550er)`; the criterion's substance — including the Braeburn regression it
  names — is unchanged, and the same test asserts the grade rewrite explicitly so the ruling is
  visible in the gate rather than only in this plan. Recorded in the REQ's Notes.

## The four known residuals the REQ owed an answer

| residual | outcome |
|---|---|
| `5–6 säuerliche Äpfel (z.B. Braeburn)` → food `Braeburn)` | **fixed** — food `Äpfel`, and AC5 fails if it ever regresses |
| `1 gehäufter Teelöffel Salz` loses its unit | **fixed** — `Teelöffel` is a known-unit alias for `Tl` |
| `Mark von 1 Vanilleschote` → `Mark` | **fixed** — by the written-order reordering above |
| `1050er Weizen- oder Dinkelmehl` names two flours | **exception** — resolves to `Dinkelmehl` noted `1050 Weizen- oder`. One line in the collection; no rule can pick one of two foods, and both are named in the note where a human can see them |

One residual this session adds, a single line, left deliberately: `1 gelbe und 1 rote Paprika`,
which names two variants without the `Je` the split keys on. It resolves to one `Paprika` noted
`gelb 1 und rot`, so both colours are visible in the row rather than lost.

## Tests

`cookbook/tests/other/test_word_repairs.py` carries AC1–AC6. AC1–AC5 are pure: the rule against
`IngredientParser` with no database, which is what makes them readable as a specification of the
rule. AC6 imports a zip of two new fixture documents end to end and asserts on the `Ingredient`
rows, the `Food` and `Unit` tables it created, and — the one that would catch a rule that
silently stopped firing — that no `Unit` exists whose name the repair file does not name.

The fixtures are `repairs_*.docx`, generated by `build_repair_fixtures.py` beside them, which
reuses REQ-006's builder for the German style ids. No document from the household collection is
committed and no real ingredient line is asserted against in the gate: every fixture line is
written for the test, to the collection's conventions.

`cookbook/tests/other/test_word_repairs_signoff.py` is AC7, on REQ-006's two-halves pattern: the
develop session commits the source half (`.devsteward/evidence/REQ-007/import-source.json`,
what the re-import actually recorded), the System Tester transcribes the observed half off the
running deployment, and the expectations are recomputed from the recorded source lines through
the repair file — so a later edit to a recipe shows up as a mismatch instead of quietly
regrading the criterion.

**REQ-006's AC3 test changes with this REQ.** It asserted the old split (`550er`, `Eier`,
`gemahlene Haselnüsse`) against the shared `canonical.docx`. Those lines now import as `550`,
`Ei` and `Haselnüsse`, so the expectations move in this commit. REQ-006's criterion is unharmed
— it is about a zip importing end to end — but the change is called out here because touching
another REQ's landed test deserves to be visible.

## Sequence

1. `word_repairs.py` + the `word.py` hook.
2. Corpus run over all 342 documents; iterate the lists until the yield is right.  *(done: the
   table above)*
3. Fixtures, AC1–AC6, and the AC7 harness; `steward gate REQ-007 develop` green.  *(done)*
4. Deploy this commit, restore the pre-import dump, re-import, capture AC7's evidence.  *(done
   twice — see below)*
5. `steward checkpoint REQ-007 develop`.

## The re-import (Decision 9)

Deployed `b8ba3903b` with `deploy/deploy.sh`, whose backup gate took and *verified restorable*
`deploy/dumps/tandoor-20260814T065442Z.dump` before anything else — that dump is the rollback
for the state this REQ replaced, and `tandoor-20260813T101030Z.dump` (REQ-006's own deploy gate,
taken before its bulk import) is what was restored. The app container was stopped for the
restore, so nothing held a connection while the schema was replaced; there are no migrations
between the two commits, so the restored database is the schema the new image expects. The
import then ran inside the app container against the live database, as **Ingrid**, whose
collection it is.

| | |
|---|---|
| documents offered | 288 |
| recipes created | **270** |
| skipped, with a reason in the log | 17 (all unfilled documents) |
| errors | 0 |
| recipes in the space | 3 → 273 |
| units in the space | 6 → 35 → **33** after the merge below |
| foods in the space | 21 → **505** |

**The zip is 288 documents, not REQ-006's 298.** Decision 12 declines the ten table-shaped
Chefkoch documents permanently, and the operator's zip is where that is realised: they are left
out rather than offered and refused. They were identified by running the parser over the
collection, not by a hand-written list, so the exclusion is reproducible.

**Two hand-entered units were merged (owner ruled 2026-08-14).** The restore brought back the
three recipes the household entered by hand before REQ-006, and with them `EL` (2 rows) and
`Prise(n)` (1 row) — spellings the repair file does not name, which would have failed AC7's
clause (a) on data that predates this REQ. Ruled: merge them into `El` and `Prise`, using the
same relation walk `MergeMixin.merge` does. Three ingredient rows changed their unit; amounts
and foods were untouched.

**The counter that disagrees, again.** As in REQ-006, `ImportLog.imported_recipes` reads 271
while the log's summary line and the `Import 5` keyword both say 270 — the base class
increments before `handle_duplicates` deletes the duplicate (`Trauben-Fenchel-Salat`, entered
by hand in 2025 and re-created by the import). AC7 grades the 270; the 271 is recorded beside
it in the evidence.

## Outcome, as the deployment now holds it

| AC7 clause | what is live |
|---|---|
| (a) every unit is a known unit, at most half of what REQ-006 left | **33 units**, every one named by the repair file, against 99 before — under the half-of-99 bar and well under the 105 the REQ quotes |
| (b) the flours are at most three foods, grade in the note | `Weizenmehl`, `Roggenmehl`, `Dinkelmehl` — one row each, no digit in any food name. The other `…mehl` foods are `Mehl`, `Weizenvollkornmehl` and `Pizzamehl`, all genuinely different flours (the last from a hand-entered recipe) |
| (c) the recipe count matches the import log | 270 under `Import 5`, and the log's summary line says the same |
| (d) three named recipes match the repair file | verified from the database before the evidence was written: `Bauernbrot mit Buttermilch` (8 rows), `Scharfes Curryhähnchen aus dem Wok` (13 rows from 12 lines — the `Je` line is two ingredients), `Makkaroni mit Schinken-Brokkoli` (12 rows). Every amount, unit, food and note equals what the committed repair file yields from the recorded source line |

The source half of AC7 is committed at `.devsteward/evidence/REQ-007/import-source.json`. The
observed half is the System Tester's to transcribe.

**One line shape the deployment found that the workstation had not.** The first re-import
produced a food called `Je`, from `Je 1 gelbe, grüne und rote Paprika` — a three-variant
spelling the two-variant split did not match, on a line the parser had already transposed. It
was fixed (`b8ba3903b`), the rule now refuses to end on a word its own lists call filler, and
the deploy and re-import were run again from the top. That is the case for Decision 10 making
the corpus run a develop obligation: no synthetic fixture would have written that line.
