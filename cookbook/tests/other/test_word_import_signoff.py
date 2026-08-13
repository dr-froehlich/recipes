"""Acceptance test for REQ-006 AC5 — manual sign-off that the collection is really in Tandoor.

AC1-AC4 prove the mechanism against synthetic fixtures whose expected output is known by
construction. What they cannot prove is that 342 real Word documents came through the
importer intact and are now on the deployed server. That needs a human oracle, so it is
graded by the System-Test phase (``steward validate REQ-006``) against evidence captured by a
session that has the fork deployed. In an ordinary full-suite run there is no deployment and
this test skips; once the engine sets DEVSTEWARD_EVIDENCE_DIR — the only context in which it
is named as an acceptance criterion — missing evidence is a hard failure, so it cannot pass by
finding nothing.

The grading has two halves, deliberately produced by two sessions that cannot see each other's
work:

**The source half**, ``.devsteward/evidence/REQ-006/import-source.json``, is written and
committed by the develop session that ran the bulk import. It records what the import log said
and, for three named recipes, the structure of the Word document each came from: its raw
ingredient lines, its step texts, its top-level folder and whether it embedded a photograph.
The System Tester never sees the collection, so it cannot produce this and cannot bend it.

**The observed half**, ``signoff.json`` in the evidence dir, is what the System Tester
transcribes off the running deployment. Nothing about the source is repeated in it::

    {
      "deployment_url": "https://...",
      "import_keyword": "Import 3",
      "import_keyword_recipe_count": 280,
      "print_subfolder_keyword_search": {"term": "Ausgedruckte", "matches": []},
      "recipes": [
        {
          "name": "Nussecken",
          "ingredients": [
            {"amount": "375", "unit": "g", "food": "Weizenmehl"},
            {"amount": "1", "unit": "Tl", "food": "Backpulver"}
          ],
          "steps": [
            "Aus den Teigzutaten einen Knetteig verarbeiten.",
            "Den Backofen auf 175°C Ober-/Unterhitze vorheizen."
          ],
          "keywords": ["Kuchen & Süße Gebäckstücke", "Import 3"],
          "image_shown": true
        }
      ]
    }

``import_keyword_recipe_count`` is the number of recipes the list shows when filtered by the
run's Import keyword. Each ``ingredients`` entry is one row of the recipe's ingredient table
as displayed — amount, unit and food in their own columns, unit empty where the row shows
none. ``steps`` is the instruction text of each step in the order the page lists them; a step
may be transcribed in full or truncated, since it is graded as a prefix. ``keywords`` is every
keyword chip on the recipe. ``print_subfolder_keyword_search.matches`` is the result of
searching the keyword list for the term — an empty list is the passing answer.

The expectations are *recomputed* here from the recorded source rather than compared to
anything the deployment reports about itself: each ingredient line is put back through
``IngredientParser``, which is what the importer used, so a later edit to a recipe on the
server shows up as a mismatch rather than silently regrading the criterion.
"""
import json
import os
import unicodedata
from pathlib import Path

import pytest

from cookbook.helper.ingredient_parser import IngredientParser

#: written and committed by the develop session that ran the bulk import
SOURCE_EVIDENCE = Path('.devsteward/evidence/REQ-006/import-source.json')

#: how much of a step the tester must transcribe for the comparison to mean anything
MINIMUM_STEP_PREFIX = 20


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation."""
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    if not raw:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-006)')
    path = Path(raw) / name
    assert path.is_file(), f'required evidence {name} was not captured into {raw}'
    return path


def _normalized(value):
    """Collapse whitespace and unicode form, so a transcription is not graded on typography."""
    return unicodedata.normalize('NFKC', ' '.join(str(value or '').split())).casefold()


def _amount(value):
    """A quantity as written on screen, as a number. German decimal commas included."""
    text = str(value or '').strip().replace(',', '.')
    if not text:
        return 0.0
    return float(text)


def test_live_signoff():
    """PASS requires all four of AC5's clauses to hold against the recorded source."""
    observed_evidence = json.loads(_require_evidence('signoff.json').read_text(encoding='utf-8'))
    assert SOURCE_EVIDENCE.is_file(
    ), (f'{SOURCE_EVIDENCE} is missing — the develop session that ran the bulk import has to record what it imported '
        f'before this criterion can be graded')
    source_evidence = json.loads(SOURCE_EVIDENCE.read_text(encoding='utf-8'))

    import_log = source_evidence['import_log']
    sources = {recipe['name']: recipe for recipe in source_evidence['recipes']}

    assert len(sources) == 3, f'AC5 grades three named recipes, the develop session recorded {len(sources)}'
    assert any(r['has_image'] for r in sources.values()), 'none of the three source documents embedded a photograph — clause (d) would grade nothing'
    assert max(len(r['steps']) for r in sources.values()), 'none of the three source documents has steps — clause (b) could not detect an ordering fault'

    # (a) the number of recipes carrying the run's Import keyword matches the import log
    assert _normalized(observed_evidence.get('import_keyword')) == _normalized(
        import_log['keyword']
    ), (f'AC5 FAIL — the recipes were counted under keyword {observed_evidence.get("import_keyword")!r}, '
        f'but the import ran under {import_log["keyword"]!r}')
    observed_count = observed_evidence['import_keyword_recipe_count']
    assert observed_count == import_log['imported_recipes'], (
        f'AC5 FAIL — the deployment shows {observed_count} recipes under '
        f'{import_log["keyword"]!r}, the import log recorded {import_log["imported_recipes"]}'
    )

    # (c, second half) no print subfolder anywhere in the keyword tree
    search = observed_evidence['print_subfolder_keyword_search']
    assert not search['matches'], (
        f'AC5 FAIL — searching the keyword list for {search["term"]!r} found {search["matches"]} — '
        f'the print subfolder level was supposed to be collapsed away'
    )

    observations = {recipe['name']: recipe for recipe in observed_evidence['recipes']}
    assert set(observations) == set(sources), (f'AC5 FAIL — the recipes transcribed {sorted(observations)} are not the three the import recorded {sorted(sources)}')

    parser = IngredientParser(None, cache_mode=False, ignore_automations=True)

    for name, source in sources.items():
        observed = observations[name]

        # (b) the ingredient list, recomputed from the source lines through the same parser
        # the importer used - quantities and units included
        expected = [parser.parse(line) for line in source['ingredients']]
        transcribed = observed['ingredients']
        assert len(transcribed) == len(expected), (f'AC5 FAIL — {name} shows {len(transcribed)} ingredients, the source document has {len(expected)}')

        for index, ((amount, unit, food, note), row) in enumerate(zip(expected, transcribed), start=1):
            assert _normalized(
                row['food']
            ) == _normalized(food), (f'AC5 FAIL — {name} ingredient {index} reads {row["food"]!r}, '
                                     f'the source line {source["ingredients"][index - 1]!r} parses to {food!r}')
            assert _amount(row['amount']) == pytest.approx(
                float(amount or 0)
            ), (f'AC5 FAIL — {name} ingredient {index} shows amount {row["amount"]!r}, '
                f'expected {amount} from {source["ingredients"][index - 1]!r}')
            if unit:
                assert _normalized(row.get('unit')) == _normalized(unit), (f'AC5 FAIL — {name} ingredient {index} shows unit {row.get("unit")!r}, '
                                                                           f'expected {unit!r}')

        # (b) the step count and the step order
        steps = observed['steps']
        assert len(steps) == len(source['steps']), (f'AC5 FAIL — {name} shows {len(steps)} steps, the source document has {len(source["steps"])}')

        for index, (shown, expected_step) in enumerate(zip(steps, source['steps']), start=1):
            shown_text, expected_text = _normalized(shown), _normalized(expected_step)
            assert len(shown_text) >= min(MINIMUM_STEP_PREFIX,
                                          len(expected_text)), (f'AC5 FAIL — {name} step {index} was transcribed as {shown!r}, '
                                                                f'too short to tell one step from another')
            assert expected_text.startswith(shown_text), (
                f'AC5 FAIL — {name} step {index} reads {shown!r}, but the source document has '
                f'{expected_step[:80]!r} in that position — the steps are out of order or altered'
            )

        # (c) the recipe carries a keyword equal to its source top-level folder
        keywords = {_normalized(k) for k in observed['keywords']}
        assert _normalized(source['top_level_folder']
                           ) in keywords, (f'AC5 FAIL — {name} came from {source["top_level_folder"]!r} '
                                           f'but carries keywords {sorted(observed["keywords"])}')
        assert _normalized(import_log['keyword']) in keywords, f'AC5 FAIL — {name} does not carry the run\'s Import keyword'
        assert not any(_normalized(search['term']) in keyword for keyword in keywords), (f'AC5 FAIL — {name} carries a print-subfolder keyword: {sorted(observed["keywords"])}')

        # (d) a recipe whose source document embedded a photograph shows that photograph
        if source['has_image']:
            assert observed['image_shown'] is True, f'AC5 FAIL — {name} embedded a photograph in Word but the recipe shows none'
