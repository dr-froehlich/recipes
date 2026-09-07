"""Acceptance test for REQ-010 AC5 — manual sign-off on the deployed fork.

AC1 proves the preference is gone from all seven layers of the source, and the vitest suite
proves the formatter against a synthetic table. Neither can see the thing that actually matters
after a removal: that a **built bundle served to a browser** still renders durations, and that
the settings page no longer offers a checkbox bound to a property the API stopped returning.

Vue does not fail loudly on that. A ``v-model`` pointing at a field the server no longer sends
renders as a permanently unchecked box that silently saves nothing, and a display path that
still expected the preference would show blanks rather than raise. Both need eyes, so this is
graded by the System-Test phase (``steward validate REQ-010``) against evidence captured by a
session that has the fork deployed. In an ordinary full-suite run there is no deployment and it
skips; once the engine sets DEVSTEWARD_EVIDENCE_DIR — the only context in which this test is
named as an acceptance criterion — missing evidence is a hard failure, so it cannot pass by
finding nothing.

The fixture is data the instance already has. Nothing is created for this test: the tester picks
a recipe with a working time under an hour and a waiting time over two hours, transcribes what
is on screen, and records the three durations those strings were rendered from. The expectations
are **recomputed here** from those durations, so a recipe the household edits later still grades
correctly.

Evidence: ``signoff.json`` in the evidence dir::

    {
      "recipe": "Pizza",
      "working_time_minutes": 45,
      "waiting_time_minutes": 2400,
      "step_time_minutes": 1440,
      "cosmetic_settings_offers_readable_time_checkbox": false,
      "settings_page_renders": true,
      "observed": {
        "detail_working_time": "45 min",
        "detail_waiting_time": "40 h",
        "list_card_chip": "40 h 45 min",
        "step_time": "24 h"
      }
    }
"""
import json
import os
from pathlib import Path

import pytest


def format_duration(minutes):
    """The format rule, reimplemented so the grader does not trust the code under test.

    Below an hour, plain minutes; from an hour up, "H h" plus " M min" when there is a
    remainder. No day rollover — 4320 is "72 h".
    """
    if minutes is None:
        return ''
    total = round(minutes)
    if total < 60:
        return f'{minutes} min'
    hours, remainder = divmod(total, 60)
    return f'{hours} h' if remainder == 0 else f'{hours} h {remainder} min'


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation."""
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    if not raw:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-010)')
    path = Path(raw) / name
    assert path.is_file(), f'required evidence {name} was not captured into {raw}'
    return path


def test_live_signoff():
    """PASS requires readable durations everywhere and no readable-time checkbox anywhere."""
    data = json.loads(_require_evidence('signoff.json').read_text(encoding='utf-8'))

    working = data.get('working_time_minutes')
    waiting = data.get('waiting_time_minutes')
    step = data.get('step_time_minutes')
    for label, value in (('working_time_minutes', working), ('waiting_time_minutes', waiting), ('step_time_minutes', step)):
        assert isinstance(value, int), f'{label} must be recorded as an integer, got {value!r}'

    # the fixture has to exercise both branches of the format rule, or the sign-off proves little
    assert working < 60, (
        f'pick a recipe whose working time is under an hour so the minutes branch is exercised; '
        f'got {working}'
    )
    assert waiting >= 120, (
        f'pick a recipe whose waiting time is at least two hours so the hours branch is '
        f'exercised; got {waiting}'
    )

    # (a) the settings page renders, and offers nothing to toggle
    assert data.get('settings_page_renders') is True, (
        'the Cosmetic settings page must still render — a checkbox bound to a removed field is '
        'the failure this criterion exists to catch'
    )
    assert data.get('cosmetic_settings_offers_readable_time_checkbox') is False, (
        'Cosmetic settings still offers the readable-time checkbox; it binds to a field the API '
        'no longer returns, so it would silently save nothing'
    )

    # (b) and (c) every surface reads what the format rule says it must
    observed = data.get('observed') or {}
    expected = {
        'detail_working_time': format_duration(working),
        'detail_waiting_time': format_duration(waiting),
        'list_card_chip': format_duration(working + waiting),
        'step_time': format_duration(step),
    }
    for surface, want in expected.items():
        got = observed.get(surface)
        assert got is not None, f'{surface} was not transcribed into the evidence'
        assert got == want, (
            f'{surface} reads {got!r}; for {data.get("recipe")!r} it must read {want!r}'
        )

    # a bare number is the regression this whole line of work exists to prevent
    for surface, got in observed.items():
        assert not str(got).strip().isdigit(), f'{surface} shows a bare number with no unit: {got!r}'
