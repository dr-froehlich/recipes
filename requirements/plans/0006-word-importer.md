# Plan 0006 — REQ-006's develop checkpoint: the Word (.docx) importer

> Authored 2026-08-13. A plan is a thinking document: how a chunk of work will be
> approached, the alternatives weighed, the sequence. It is not a contract (REQs are).

## Context

Advances [REQ-006](../REQ-006.md) — 342 Word documents on a Syncthing share become recipes
in the deployed instance, through an importer that still works next year without a
developer.

The REQ froze the hard thinking: a `Word` Integration subclass rather than a conversion
script (Decision 1), a pure parser split from a thin integration (2), ingredient lines
handed to the existing `IngredientParser` (3), one Step per Word paragraph (4), component
sections as named Steps (5), table-shaped documents skipped rather than guessed at (6),
empty documents skipped and folder curation left to the operator (7), top-level folder →
keyword with the print subfolders collapsed (8), the full-corpus run as a develop
obligation rather than a validation criterion (9), the bulk import behind REQ-002's
verified dump (10), first embedded photo only (11), no upstream offer (12).

Corpus root on this workstation: `/mnt/c/home/Persönlich/Ingrid/Rezepte` — 342 `.docx`,
46 MB total, largest 2.4 MB. Comfortably inside `MAX_ZIP_FILE_COUNT` (2000),
`MAX_ZIP_TOTAL_SIZE` (500 MB) and `MAX_ZIP_FILE_SIZE` (10 MB), so the whole collection can
go in as one zip. Nothing about that path is committed or read by the application; it is a
develop-session input.

Shape of the work: one new pure module, one new integration, four small edits (dispatcher,
form choices, frontend registry, `requirements.txt`), a committed fixture set with its
generator, one test module with the four gate criteria, and one manual-sign-off harness.

## What the corpus actually looks like

Re-measured this session rather than trusted from the REQ, because every design choice
below is keyed to it.

| Signal | Count |
|---|---|
| documents | 342 |
| `Titel`-styled name | 311 |
| `Zutaten` heading (any form) | 286 exact + ~45 qualified |
| `Zubereitung` heading | 310 |
| bulleted (`w:numPr`) paragraphs | 2750 |
| documents containing a table | 16 |
| documents with no `Titel` | 31 |
| embedded media | 443 (432 `.jpeg`, 3 `.png`, 8 `.wmf`) |

Two findings changed the design:

**Style ids are German, style *names* are not.** The corpus carries
`w:styleId="Titel" / "berschrift1" / "Listenabsatz"` — Word strips non-ASCII from style
ids, which is why the heading id has lost its `Ü`. python-docx resolves a built-in style to
its canonical English name, so `paragraph.style.name` reads `'Title'`, `'Heading 1'`,
`'List Paragraph'` on these very files. The parser therefore matches on **English style
names** and stays English-only code, while the German words it looks for in *content*
(`Zutaten`, `Zubereitung`) are document data, not UI strings. The committed fixtures are
built with the German style ids so this bridge is what the gate actually exercises.

**Bulleted ≠ ingredient.** `Erbsensuppe mit Croûtons` ends with four bulleted "Tipps"
paragraphs *after* the `Zubereitung` heading. Ingredient-ness is a property of the section a
paragraph sits in, never of its bullet. The same document also shows the reverse: a list
paragraph inside an instruction section is a perfectly good step, and dropping it would lose
the tips.

## Approach

### `cookbook/helper/word_parser.py` — the pure half

Modelled on `cooklang_parser.py`: no Django, no models, no request, no database. Takes
`.docx` bytes, returns a `WordRecipe` dataclass (name, servings, servings_text, components,
image bytes + file type) or raises. Standalone-runnable is the point — Decision 9's corpus
run is a loop over this function, and the model-writing half must not be in the way.

Body blocks are walked in document order (`w:p` and `w:tbl` children of `w:body`), carrying
one piece of state: which section we are in.

- **Title** — the first `Title`-styled paragraph.
- **`Zutaten…` heading** — opens an ingredient section.
- **`Zubereitung…` heading** — opens an instruction section.
- **Any other heading** — opens an instruction section too, and the heading text is
  recorded in `ignored_headings` rather than silently dropped (`Planungsbeispiel`,
  `Befüllen`, `DEKOR` in the corpus).
- **Table** — never read for content; only the fact that one was seen is remembered.

Rejections are exceptions carrying a `reason`, checked in this order after the walk:

1. no ingredients **and** a table was seen → `UnparseableDocument`
2. no ingredients **and** no steps → `EmptyDocument`

The order matters and is not cosmetic. `Laugenbrezn` — the Chefkoch shape — has 18 body
paragraphs, but with no `Zubereitung` heading none of them is in an instruction section, so
it reads as 0 ingredients *and* 0 steps. Checking "empty" first would file the exact
documents Decision 6 is about under the wrong reason, and the import log is the only place
the household ever learns which sixteen documents need re-saving.

#### Fork A — the first `Zutaten` heading: yield or component?

The REQ's Requirement section wants two things from the same heading. "**Servings** from the
ingredient heading's trailing text … anything unresolvable leaves the count at its default
and keeps the phrase as text" reads the first heading as a yield. "**Components**: each
*further* `Zutaten für X` heading opens a new named step" reads only subsequent ones as
components. Applied literally to the corpus that is wrong for ~20 documents: `Nussecken`
opens with `Zutaten für den Teig`, and a recipe whose servings render as "1 den Teig" is
worse than no servings at all.

Three rules were considered:

| Rule | `Zutaten für 4 Personen` | `Zutaten für den Teig` (with more sections) | Verdict |
|---|---|---|---|
| Literal: first heading is always the yield | 4 / "Personen" ✓ | 1 / "den Teig" ✗ | breaks 20 real documents |
| Count-based: a lone `Zutaten` heading is a yield, otherwise all are components | 4 / "Personen" ✓ | component "Teig" ✓ | breaks AC1, whose one fixture needs both a yield *and* a component section |
| **Chosen**: a number wins; otherwise a heading with siblings is a component | 4 / "Personen" ✓ | component "Teig" ✓ | holds everywhere |

The chosen rule in one sentence: **the first ingredient heading is the yield heading, unless
its trailing phrase contains no leading number and the document has further ingredient
headings — then it is a component like the rest.** `Zutaten für die ganze Familie` in a
document with a single ingredient section still leaves the count at 1 and keeps the phrase as
servings text, which is the unresolvable case the REQ asks for; `Zutaten für den Teig` in a
document that goes on to `Zutaten für den Belag` is a component. Digits and the German number
words `ein…zwölf` both resolve.

#### Fork B — `Zubereitung für die Klopse` arriving after all the ingredient sections

`Königsberger Klopse` lists *both* ingredient sections first and *then* both instruction
sections. Attaching instructions to "the component currently open" would pour the Klopse
method into the Kapernsoße. So a `Zubereitung <X>` heading whose `<X>` matches an already-open
component by name routes its paragraphs to *that* component; everything else appends to the
current one. Four or five documents need it, it is ten lines, and the failure it prevents is
the silent kind.

### `cookbook/integration/word.py` — the thin half

Maps `WordRecipe` onto `Recipe` / `Step` / `Ingredient` / `Keyword`, with ingredients through
`IngredientParser` exactly as `chowdown` and `nextcloud_cookbook` do.

Per component: one `Step` per instruction paragraph in document order, `Step.order` running
across the whole recipe, the component's name on its first step, that component's ingredients
attached to that same first step. A component with ingredients but no instructions still gets
one (empty) step to carry them.

#### Fork C — `do_import` is overridden rather than inherited

The base `Integration.do_import` reads a zip entry and calls
`get_recipe_from_file(BytesIO(...))` — **the entry's path is gone by then**, and Decision 8
needs it. Options weighed:

- *Pair recipes back to paths by iteration index*, remembered in `import_file_name_filter`.
  Smallest diff, but it depends on the base looping over the filtered list in the same order
  it filtered — an upstream reordering would not fail, it would attach the wrong category
  keyword to every recipe. Silent-wrong on rebase is the one failure mode this fork cannot
  afford.
- *Pair by content hash.* Survives reordering, but the collection has 13 filename collisions
  from the photo-work folders and duplicate content would land on an arbitrary path.
- **Chosen: override `do_import`.** ~50 lines that read top to bottom, keep `safe_read` /
  `get_zip_file` / `handle_duplicates` / the `Import N` keyword / the log trailer, and add
  nothing to the core. The base method is a 100-line `if/elif` chain with `isinstance` checks
  for six named integrations; it is not a reuse surface worth bending the design around, and
  a new file cannot conflict on rebase.

#### Fork D — collapsing the print subfolders without hardcoding them

Decision 8 wants `Fleisch/Ausgedruckte Rezepte mit Bild/Gulasch.docx` to yield the keyword
`Fleisch`. Matching that literal German folder name in forked core code would put one
household's workflow vocabulary into the fork, which REQ-001 Decision 5 exists to prevent.

The general rule does the same job: **the keyword is the first path segment, and deeper
segments are simply not used.** The print level disappears because nothing ever looks at it,
no string is hardcoded, and the rule reads the same to a stranger. A common leading directory
shared by *every* entry is stripped first, so zipping the collection folder itself does not
collapse all 342 recipes onto one useless keyword.

### Image

First embedded image in document order whose extension is a raster type Tandoor's
`handle_image` can open — which drops the 8 `.wmf` files without a special case. Attaching is
wrapped so that a picture Pillow cannot read costs the picture, not the recipe.

### Registries (AC4)

`ImportExportBase.WORD` + a `('WORD', 'Word')` choice in `cookbook/forms.py`, a
`get_integration` branch, and a row in `vue3/src/utils/integration_utils.ts`. That array is
hand-maintained and *not* generated from OpenAPI, so no client regeneration and none of the
plugin-file trap in CLAUDE.md. `ImportLog.type` is a plain `CharField`, so no migration.

### Fixtures and tests

`cookbook/tests/other/test_data/Word/` holds seven committed `.docx` written for the tests,
plus `build_fixtures.py` that generated them — the script is the reviewable source, the
binaries are what the gate reads. It post-processes python-docx's output to rename the style
ids to `Titel` / `berschrift1` / `Listenabsatz`, so the tests exercise the same
German-id-to-English-name bridge the real corpus depends on. No document from the collection
is committed.

AC3's zip is assembled from those files in the test: a zip is a container, not content, and
building it in the test keeps the folder layout it asserts about visible in the test.

### The corpus run (Decision 9) and AC5

Not an acceptance criterion — an obligation of this session. Run the parser over all 342
documents, record the outcome per file, fix what it turns up, repeat. Then deploy with
REQ-002's script (which takes and verifies its own restorable dump), bulk-import the zip, and
record the evidence AC5 grades: the import log's recipe count and three named recipes
transcribed from their source documents.

## Sequence

1. Parser + fixtures + generator.
2. Integration + the four registry edits.
3. The four gate tests green (`steward gate REQ-006 develop`).
4. Corpus run over all 342; iterate until the yield is right; record the outcome per file.
5. Decide the Chefkoch remedy (re-save vs. follow-on REQ) and record it in the REQ's Notes.
6. Deploy, bulk import, capture AC5 evidence.
7. `steward checkpoint REQ-006 develop`.

## Outcome of the corpus run (Decision 9)

Parser over all **342** documents: **280 parsed, 15 refused as table-shaped, 47 yielded
nothing, 0 crashed**, and `IngredientParser` flagged **none** of the 2680 ingredient lines
it produced. Integration end to end over the curated zip (see below): **271 recipes, 2639
ingredients, 1323 steps, 226 photographs, 22 keywords, 0 errors, 0 duplicate names.**

The 22 keywords are the 20 category folders that contributed a recipe plus `Import` /
`Import 1`. Neither `Ausgedruckte Rezepte mit Bild` nor `… ohne Bild` appears anywhere —
Fork D's general rule does what Decision 8 asked for, on the real tree.

**What the 47 empty documents are.** 27 are the blank `Allg. Vorlage <category>.docx`
templates and the `Rezeptecover*.docx` folder covers. 17 are recipes the household created
and never filled in — `Titel`, a `Zutaten` heading with one empty bullet, a `Zubereitung`
heading with one empty paragraph, and nothing else (`Krautsalat`, `Rinderschmorbraten`,
`Mousse au chocolat`, …). 3 are genuinely non-canonical: `Sally Macarons` has no styles at
all, and `Gulasch für 10 Personen` (in two copies) writes "Zutaten" and "Zubereitung" as
ordinary body text. Skipping all of them is the right answer; the 17 unfilled stubs are a
finding for the household, not for the code.

**The operator's curation (Decision 7).** The imported zip holds **298** of the 342: the
`Ausgewählte Bilder/` and `Food-Fotografie/` folders are excluded because they re-copy
recipes for photo work, the 25 `Allg. Vorlage` templates because they are not recipes, and
the root `Rezeptecover.docx` likewise. That removed 35 documents that would have been skipped
anyway and **9 blank templates that would otherwise have imported as junk recipes** — which
is the case for curating rather than trusting the empty-document rule alone.

**Two documents lose a sub-heading, no ingredients.** `Rosinenschnecken` and
`Gemüsepfannkuchen` write one of their `Zutaten für X` lines as ordinary body text instead of
a heading. Those lines are dropped and their bullets fold into the preceding component, so
every ingredient still arrives but one component boundary is lost. A style-independent
fallback would rescue two documents at the cost of Decision 6's "only the canonical style
profile" — not worth it.

**The Chefkoch remedy (REQ Notes, "Known gap, homed not deferred").** After curation
**10 distinct documents** remain refused: `Krapfen Hümbs`, `Krapfen Pflaumenmus`,
`Laugenbrezn`, `Rindfleisch-Pie`, `Rosmarin-Ciabatta`, `Sachertorte das große Backen`,
`Walnusskuchen`, `Feta Cheesecake`, `Muffins-mit-Zitronengras`, `Omas Kartoffelsuppe`. Ten is
small enough that the REQ's first remedy wins: **re-save them in Word to the household's own
convention** — a `Titel`, `Zutaten`/`Zubereitung` headings, bulleted ingredients — and re-run
the importer on just those. That costs no code, improves the source of truth, and needs no
follow-on REQ. A second parser profile is recorded as rejected: it would carry a whole
inverted layout's worth of guessing for ten files that the household can fix in an evening.

## The bulk import (Decision 10)

Deployed `505186e8a` with `deploy/deploy.sh`, whose backup gate took and *verified restorable*
`deploy/dumps/tandoor-20260813T101030Z.dump` before any migration ran — that dump is the
rollback for everything below. The import then ran inside the app container against the live
database, as **Ingrid**, whose collection it is.

| | |
|---|---|
| documents offered | 298 |
| recipes created | **270** |
| skipped, with a reason in the log | 27 (10 table-shaped, 17 unfilled) |
| errors | 0 |
| photographs attached | 225 |
| category keywords created | 20, no print subfolder among them |
| recipes in the space | 3 → 273 |

**One deduplication, and a counter that disagrees because of it.** `Trauben-Fenchel-Salat`
already existed, entered by hand in 2025; the Word document of the same name was created,
recognised as a duplicate and deleted, leaving the original untouched. That is
`handle_duplicates` doing its job — but the base class increments `il.imported_recipes`
*before* calling it, so the `ImportLog.imported_recipes` field reads **271** while the log's
own summary line reads "Imported 270 recipes." and the Import keyword carries **270**.

The gap is upstream's, not this REQ's, and it is not worth a core patch: the summary line and
the keyword agree with each other and with reality. AC5's source evidence records the graded
number as 270 and carries the 271 beside it under `import_log_counter_field`, with the
duplicate named, so the discrepancy is visible in the record rather than reconciled away.
