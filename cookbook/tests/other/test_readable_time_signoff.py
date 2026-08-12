"""Acceptance test for REQ-003 AC4 — manual sign-off on the deployed fork.

AC1 proves the formatter itself against a synthetic table; there is no production corpus
that can surprise a pure function of one integer. What this criterion checks is *wiring*:
that the preference actually reaches the read-only duration displays in a built bundle
served to a browser, and that switching it off puts the raw minutes back.

That needs a human oracle, so it is graded by the System-Test phase
(``steward validate REQ-003``) against evidence captured by a session that has the fork
deployed. In an ordinary full-suite run there is no deployment and the test skips; once the
engine sets DEVSTEWARD_EVIDENCE_DIR — the only context in which this test is named as an
acceptance criterion — missing evidence is a hard failure, so it cannot pass by finding
nothing.

The fixture is data the household instance already has: the **Pizza** recipe (working 45,
waiting 2400, longest step 1440 as of 2026-08-12), which covers both branches that matter —
a whole number of hours, and hours with a remainder once the card sums the two. Nothing is
created for this test. The tester transcribes what is on screen; the expectation is
recomputed here from the durations they record, so the criterion survives the household
editing the recipe.

Evidence: ``signoff.json`` in the evidence dir::

    {
      "recipe": "Pizza",
      "working_time_minutes": 45,
      "waiting_time_minutes": 2400,
      "step_time_minutes": 1440,
      "observed": {
        "detail_working_time": "45 min",
        "detail_waiting_time": "40 h",
        "list_card_chip": "40 h 45 min",
        "step_timer_button": "24 h"
      },
      "observed_with_preference_off": {
        "detail_working_time": "45 min",
        "detail_waiting_time": "2400 min",
        "list_card_chip": "2445 min",
        "step_timer_button": "1440 min"
      }
    }

``observed`` is read with "Readable Times" checked in Cosmetic settings,
``observed_with_preference_off`` with it unchecked and the page reloaded. Transcribe the
text only — not the icon, not the "Working Time" caption underneath. The card chip is the
recipe's card in the list, which shows working + waiting summed.
"""
import json
import os
from pathlib import Path

import pytest

DURATION_KEYS = ('working_time_minutes', 'waiting_time_minutes', 'step_time_minutes')


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation."""
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    if not raw:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-003)')
    path = Path(raw) / name
    assert path.is_file(), f'required evidence {name} was not captured into {raw}'
    return path


def _expected(minutes, readable):
    """The string the UI must show for `minutes`, independently of the TypeScript.

    Deliberately a second implementation of the rule in vue3/src/utils/duration_utils.ts
    rather than a call into it: a manual criterion graded against the very code it is
    checking would pass whatever that code happened to do.
    """
    if not readable or minutes < 60:
        return f'{minutes} min'
    hours, remainder = divmod(minutes, 60)
    return f'{hours} h' if remainder == 0 else f'{hours} h {remainder} min'


def _normalized(value):
    """Collapse the whitespace a transcription picks up, so ' 40  h ' == '40 h'."""
    return ' '.join(str(value).split())


def test_live_signoff():
    """PASS requires all eight transcribed strings to be what the durations imply."""
    data = json.loads(_require_evidence('signoff.json').read_text(encoding='utf-8'))

    assert _normalized(data.get('recipe', '')), 'signoff.json does not name the recipe that was observed'

    for key in DURATION_KEYS:
        assert key in data, f'{key} missing from signoff.json — the observation cannot be graded without it'
        assert isinstance(data[key], int), f'{key} must be a whole number of minutes, got {data[key]!r}'

    working, waiting, step = (data[key] for key in DURATION_KEYS)

    # A surface with nothing over an hour on it would let a broken formatter pass: below 60
    # the readable and raw renderings are identical by design.
    assert max(waiting, step) >= 60, (
        f'the observed recipe has no duration of an hour or more (waiting {waiting}, step {step}) — '
        f'it cannot show the difference this criterion is about'
    )

    surfaces = {
        'detail_working_time': working,
        'detail_waiting_time': waiting,
        'list_card_chip': working + waiting,
        'step_timer_button': step,
    }

    for block, readable in (('observed', True), ('observed_with_preference_off', False)):
        assert block in data, f'{block} missing from signoff.json — that half of the observation was not recorded'
        for field, minutes in surfaces.items():
            assert field in data[block], f'{block}.{field} was not recorded'
            want = _expected(minutes, readable)
            got = _normalized(data[block][field])
            assert got == want, (
                f'AC4 FAIL — {block}.{field} shows {got!r}, expected {want!r} for {minutes} minutes'
            )
