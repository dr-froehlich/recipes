"""Acceptance test for REQ-007 AC8 — manual sign-off that the repaired collection is live.

AC1-AC7 prove the rule and the importer against fixtures whose expected output is known by
construction. What they cannot prove is that 2639 real ingredient lines came through the repair
and are now on the deployed server as foods you would buy. That needs a human oracle, so it is
graded by the System-Test phase (``steward validate REQ-007``) against evidence captured by a
session that has the fork deployed. In an ordinary full-suite run there is no deployment and
this test skips; once the engine sets DEVSTEWARD_EVIDENCE_DIR - the only context in which it is
named as an acceptance criterion - missing evidence is a hard failure, so it cannot pass by
finding nothing.

Same two-halves grading as REQ-006's sign-off, and for the same reason: the two halves are
produced by two sessions that cannot see each other's work.

**The source half**, ``.devsteward/evidence/REQ-007/import-source.json``, is written and
committed by the develop session that ran the re-import. It records what the import log said,
what the run made of the collection in aggregate (the units it created, the flour foods it left
behind), and, for three named recipes, the raw ingredient lines of the Word document each came
from. The System Tester never sees the collection, so it cannot produce this and cannot bend
it.

**The observed half**, ``signoff.json`` in the evidence dir, is what the System Tester
transcribes off the running deployment::

    {
      "unit_list": ["Becher", "Blatt", "Bund", "..."],
      "food_search_mehl": ["Mehl", "Weizenmehl", "Weizenmehl 1050", "Weizenmehl 550"],
      "food_tree": {"Weizenmehl": ["Weizenmehl 1050", "Weizenmehl 550"],
                    "Paprika": ["Paprika gelb", "Paprika rot"]},
      "import_keyword": "Import 6",
      "import_keyword_recipe_count": 270,
      "recipes": [
        {
          "name": "Nussecken",
          "ingredients": [
            {"amount": "375", "unit": "g", "food": "Weizenmehl 550", "note": ""},
            {"amount": "1", "unit": "Tl", "food": "Backpulver", "note": ""}
          ]
        }
      ]
    }

``unit_list`` is every unit name the unit list page shows. ``food_search_mehl`` is every food
name the food list shows when filtered to "Mehl". ``food_tree`` records, for the two head nouns
AC8 names, the children the food list shows indented beneath them. ``import_keyword_recipe_count`` is the number
of recipes the recipe list shows when filtered by the run's Import keyword. Each ``ingredients``
entry is one row of a recipe's ingredient table as displayed - amount, unit, food and note in
their own columns, empty where the row shows none.

Nothing that identifies the deployment goes in the file. The tester reaches it through the
gitignored ``deploy/target.env``; this evidence is committed to a public repository, and
REQ-002 Decision 3 keeps the household's hostname and public recipe domain out of it.

The three recipes' expectations are *recomputed* here from the recorded source lines through the
committed repair file - the same code the importer ran - rather than compared to anything the
deployment reports about itself. A later edit to a recipe on the server therefore shows up as a
mismatch instead of quietly regrading the criterion.
"""
import json
import os
import unicodedata
from pathlib import Path

import pytest

from cookbook.helper.ingredient_parser import IngredientParser
from cookbook.integration.word_repairs import KNOWN_UNITS, prepare_line, repair

#: written and committed by the develop session that ran the re-import
SOURCE_EVIDENCE = Path('.devsteward/evidence/REQ-007/import-source.json')


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation."""
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    if not raw:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-007)')
    path = Path(raw) / name
    assert path.is_file(), f'required evidence {name} was not captured into {raw}'
    return path


def _normalized(value):
    """Collapse whitespace and unicode form, so a transcription is not graded on typography."""
    return unicodedata.normalize('NFKC', ' '.join(str(value or '').split())).casefold()


def _amount(value):
    """A quantity as written on screen, as a number. German decimal commas included."""
    text = str(value or '').strip().replace(',', '.')
    return float(text) if text else 0.0


def _expected_rows(lines):
    """What the committed repair file makes of a document's ingredient lines."""
    parser = IngredientParser(None, cache_mode=False, ignore_automations=True)
    return [repair(prepared, *parser.parse(prepared)) for line in lines for prepared in prepare_line(line)]


def test_live_signoff():
    """PASS requires all five of AC8's clauses to hold against the recorded source."""
    observed = json.loads(_require_evidence('signoff.json').read_text(encoding='utf-8'))
    assert SOURCE_EVIDENCE.is_file(
    ), (f'{SOURCE_EVIDENCE} is missing — the develop session that ran the re-import has to record '
        f'what it imported before this criterion can be graded')
    source = json.loads(SOURCE_EVIDENCE.read_text(encoding='utf-8'))

    import_log = source['import_log']
    sources = {recipe['name']: recipe for recipe in source['recipes']}
    assert len(sources) == 3, f'AC8 grades three named recipes, the develop session recorded {len(sources)}'

    # (a) every unit on the deployment is a unit. There is deliberately no ceiling on how
    # many: the rework trades a longer list for losing nothing (REQ-007 Decision 13), and the
    # first implementation's shrinkage target would now grade the fix as a failure.
    known = {_normalized(name) for name in KNOWN_UNITS.values()}
    units = observed['unit_list']
    unknown = [name for name in units if _normalized(name) not in known]
    assert not unknown, f'AC8 FAIL — the unit list still shows {unknown}, which the repair file does not name as units'

    # (b) no food name is malformed, and a graded flour is named after its family so that all
    # of them sort together rather than under their grade
    flours = observed['food_search_mehl']
    assert not [name for name in flours if ',' in name], 'AC8 FAIL — a food name contains a comma'
    stray = [name for name in flours if name.split() and name.split()[0][:1].isdigit()]
    assert not stray, f'AC8 FAIL — {stray} lead with their grade, so the flours no longer sort together'
    for name in flours:
        assert _normalized(name.split()[0]) not in known, f'AC8 FAIL — the food {name!r} still carries a unit word'

    # (e) ...and the qualified foods hang under a bare head noun, which is what makes one
    # flour stand in for another in the make-now filter (REQ-007 Decision 16)
    tree = observed['food_tree']
    for parent in ('Weizenmehl', 'Paprika'):
        assert parent in tree, f'AC8 FAIL — the food list shows no bare {parent!r} for its qualified foods to hang under'
        children = tree[parent]
        assert children, f'AC8 FAIL — {parent!r} has no children, so the qualified foods are sitting at the root'
        for child in children:
            assert _normalized(child).startswith(_normalized(parent)), f'AC8 FAIL — {child!r} is a child of {parent!r} but is not named after it'

    # the grades reached the food names rather than stopping in a note nobody sees, which is
    # the whole reason the first implementation's sign-off was declined
    assert any(character.isdigit() for child in tree['Weizenmehl'] for character in child), (
        'AC8 FAIL — no flour under Weizenmehl carries its grade in the name'
    )

    # (c) the recipes carrying the run's Import keyword are the ones the import log counted
    assert _normalized(observed.get('import_keyword')) == _normalized(
        import_log['keyword']
    ), (f'AC8 FAIL — the recipes were counted under keyword {observed.get("import_keyword")!r}, '
        f'but the import ran under {import_log["keyword"]!r}')
    assert observed['import_keyword_recipe_count'] == import_log['imported_recipes'], (
        f'AC8 FAIL — the deployment shows {observed["import_keyword_recipe_count"]} recipes under '
        f'{import_log["keyword"]!r}, the import log recorded {import_log["imported_recipes"]}'
    )

    # (d) every ingredient row of the three named recipes, recomputed from the source lines
    observations = {recipe['name']: recipe for recipe in observed['recipes']}
    assert set(observations) == set(sources), (f'AC8 FAIL — the recipes transcribed {sorted(observations)} are not the three '
                                               f'the re-import recorded {sorted(sources)}')

    for name, recorded in sources.items():
        expected = _expected_rows(recorded['ingredients'])
        rows = observations[name]['ingredients']
        assert len(rows) == len(expected), (f'AC8 FAIL — {name} shows {len(rows)} ingredient rows, its source document yields '
                                            f'{len(expected)} through the repair file')

        for index, ((amount, unit, food, note), row) in enumerate(zip(expected, rows), start=1):
            where = f'AC8 FAIL — {name} ingredient {index}'
            assert _normalized(row['food']) == _normalized(food), f'{where} reads {row["food"]!r}, the repair file yields {food!r}'
            assert _amount(row['amount']) == pytest.approx(float(amount or 0)), f'{where} shows amount {row["amount"]!r}, expected {amount}'
            assert _normalized(row.get('unit')) == _normalized(unit), f'{where} shows unit {row.get("unit")!r}, expected {unit!r}'
            assert _normalized(row.get('note')) == _normalized(note), f'{where} shows note {row.get("note")!r}, expected {note!r}'

            # the two shapes AC7 names as failures outright, wherever they turn up
            assert ',' not in row['food'], f'{where} is a food name containing a comma'
            assert _normalized(row['food'].split()[0]) not in known, f'{where} is a food that still carries a unit word'
