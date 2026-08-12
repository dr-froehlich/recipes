"""Acceptance test for REQ-003 AC4 — manual sign-off on the deployed fork.

AC1 proves the formatter itself against a synthetic table; there is no production corpus
that can surprise a pure function of one integer. What this criterion checks is *wiring*:
that the preference actually reaches the four read-only duration displays in a built bundle
served to a browser, and that switching it off puts the raw minutes back.

That needs a human oracle, so it is graded by the System-Test phase
(``steward validate REQ-003``) against evidence captured by a session that has the fork
deployed. In an ordinary full-suite run there is no deployment and the test skips; once the
engine sets DEVSTEWARD_EVIDENCE_DIR — the only context in which this test is named as an
acceptance criterion — missing evidence is a hard failure, so it cannot pass by finding
nothing.

Evidence: ``signoff.json`` in the evidence dir, an object with these four boolean keys, all
observed on a recipe whose waiting time is 4320 minutes with a step timed at 4320 minutes,
signed in as a normal user:

  detail_page_shows_hours    the recipe detail page renders the waiting time as "72 h",
                             not "4320 min"
  list_card_shows_unit       the recipe's card in the list shows a time chip carrying a
                             unit, not a bare number
  step_button_shows_hours    the step's timer button shows "72 h"
  toggle_restores_minutes    unchecking "Readable Times" in Cosmetic settings restores the
                             raw-minute rendering on all three after a reload
"""
import json
import os
from pathlib import Path

import pytest

OBSERVATIONS = (
    'detail_page_shows_hours',
    'list_card_shows_unit',
    'step_button_shows_hours',
    'toggle_restores_minutes',
)


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation."""
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    if not raw:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-003)')
    path = Path(raw) / name
    assert path.is_file(), f'required evidence {name} was not captured into {raw}'
    return path


def test_live_signoff():
    """PASS requires all four observations on the running deployment."""
    data = json.loads(_require_evidence('signoff.json').read_text(encoding='utf-8'))

    for key in OBSERVATIONS:
        assert key in data, f'{key} missing from signoff.json — the observation was not recorded'
        assert data[key] is True, f'AC4 FAIL — {key} was not observed: {data.get(key)!r}'
