"""Acceptance test for REQ-008 AC5 — manual sign-off on the deployed fork.

AC1-AC4 prove the arithmetic and the lock against synthetic fixtures. What this criterion
checks is *wiring*: that the two-box step editor reaches a built bundle, that a saved split
survives a reopen, that the recipe's own time fields are actually disabled where the API would
refuse them and still editable where it would not, and that the totals row and the list card
agree with the step values printed beneath them.

That needs a human oracle, so it is graded by the System-Test phase (``steward validate
REQ-008``) against evidence captured by a session that has the fork deployed. In an ordinary
full-suite run there is no deployment and the test skips; once the engine sets
DEVSTEWARD_EVIDENCE_DIR — the only context in which this test is named as an acceptance
criterion — missing evidence is a hard failure, so it cannot pass by finding nothing.

The tester works with **two** recipes on the instance: one that already has at least two timed
steps (``derived``), and one whose steps carry no times at all (``manual``). Nothing is created
except, if no such recipe exists, the times the tester enters.

Evidence: ``signoff.json`` in the evidence dir::

    {
      "derived": {
        "recipe": "Sauerteigbrot",
        "editor_shows_working_and_waiting_boxes": true,
        "legacy_step_opened_as": {"working": 0, "waiting": 720},
        "steps": [
          {"working": 10, "waiting": 240},
          {"working": 15, "waiting": 720}
        ],
        "steps_after_reopen": [
          {"working": 10, "waiting": 240},
          {"working": 15, "waiting": 720}
        ],
        "recipe_time_fields_disabled": true,
        "detail_working_time": "25 min",
        "detail_waiting_time": "16 h",
        "list_card_chip": "16 h 25 min"
      },
      "manual": {
        "recipe": "Pfannkuchen",
        "recipe_time_fields_disabled": false,
        "entered": {"working_time": 20, "waiting_time": 5},
        "persisted_after_reload": {"working_time": 20, "waiting_time": 5}
      }
    }

``steps`` is what the tester typed into each timed step's Working and Waiting boxes, in step
order; ``steps_after_reopen`` is what those boxes showed after saving and reopening the editor.
``legacy_step_opened_as`` is how a step that had only an elapsed time before this deploy first
appeared — it must read as fully unattended, which is the REQ's stated and accepted limitation,
not a bug. The three display strings are transcribed text only, not the icons or the captions.

Expectations are recomputed here from the recorded step values, so a recipe edited between
capture and grading is still graded correctly.
"""
import json
import os
from pathlib import Path

import pytest

DURATION_KEYS = ('working', 'waiting')


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation."""
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    if not raw:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-008)')
    path = Path(raw) / name
    assert path.is_file(), f'required evidence {name} was not captured into {raw}'
    return path


def _normalized(value):
    """Collapse the whitespace a transcription picks up, so ' 16 h  25 min ' == '16 h 25 min'."""
    return ' '.join(str(value).split())


def _readable(minutes):
    """The string REQ-003's formatter must produce for a duration.

    Deliberately a second implementation of vue3/src/utils/duration_utils.ts rather than a call
    into it: a manual criterion graded against the very code it checks would pass whatever that
    code happened to do.
    """
    total = round(minutes)
    if total < 60:
        return f'{total} min'
    hours, remainder = divmod(total, 60)
    return f'{hours} h' if remainder == 0 else f'{hours} h {remainder} min'


def test_live_signoff():
    signoff = json.loads(_require_evidence('signoff.json').read_text(encoding='utf-8'))

    derived = signoff['derived']
    manual = signoff['manual']

    assert len(derived['steps']) >= 2, 'the derived recipe must have at least two timed steps'
    for entry in derived['steps'] + derived['steps_after_reopen']:
        for key in DURATION_KEYS:
            assert isinstance(entry[key], int) and entry[key] >= 0, f'{key} must be a non-negative integer'

    # (a) the single Time box became two, and a step that had only an elapsed time reads as all
    # waiting. That last part is the REQ's accepted limitation made visible on purpose: no
    # migration can infer which legacy durations were attended, so a legacy step opening with a
    # non-zero working time would mean the conversion invented data.
    assert derived['editor_shows_working_and_waiting_boxes'] is True, \
        'the step editor still shows a single Time input'
    opened = derived['legacy_step_opened_as']
    assert opened['working'] == 0, 'a legacy step must open with no working time'
    assert opened['waiting'] > 0, 'a legacy step must open with its full duration as waiting'

    # (b) what the tester typed is what the editor shows again
    assert derived['steps_after_reopen'] == derived['steps'], \
        'the step durations did not survive a save and a reopen'

    # (c) the editor refuses what the API would refuse
    assert derived['recipe_time_fields_disabled'] is True, \
        'a recipe with timed steps still offers editable Working/Waiting Time fields'

    # (d) the times row agrees with the step values printed beneath it
    working = sum(entry['working'] for entry in derived['steps'])
    waiting = sum(entry['waiting'] for entry in derived['steps'])
    assert _normalized(derived['detail_working_time']) == _readable(working)
    assert _normalized(derived['detail_waiting_time']) == _readable(waiting)

    # (e) the card sums working and waiting, as it always has
    assert _normalized(derived['list_card_chip']) == _readable(working + waiting)

    # (f) the whole imported collection must still behave exactly as before
    assert manual['recipe_time_fields_disabled'] is False, \
        'a recipe with no step times must still offer editable Working/Waiting Time fields'
    assert manual['persisted_after_reload'] == manual['entered'], \
        'a hand-entered total on an untimed recipe did not persist'
