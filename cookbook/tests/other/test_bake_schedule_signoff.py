"""Acceptance test for REQ-004 AC5 — manual sign-off on the deployed fork.

AC1-AC4 prove the scheduler, the formatter, the weekday/query-param round trip and the
sub-recipe guard against synthetic tables; there is no production corpus that can surprise a
pure function of a datetime and a list of integers. What this criterion checks is *wiring*:
that the finish-time control reaches both ``RecipeView`` layouts in a built bundle served to
a browser, that clearing really clears, and that the planner hand-off survives the round trip
through a query param.

That needs a human oracle, so it is graded by the System-Test phase
(``steward validate REQ-004``) against evidence captured by a session that has the fork
deployed. In an ordinary full-suite run there is no deployment and the test skips; once the
engine sets DEVSTEWARD_EVIDENCE_DIR — the only context in which this test is named as an
acceptance criterion — missing evidence is a hard failure, so it cannot pass by finding
nothing.

The fixture is data the household instance already has (the **Pizza** recipe) plus one meal
plan entry for it that the operator creates as part of setting up the observable state. The
tester transcribes what is on screen; every expectation is recomputed here from the step
durations and the finish time they record, so the criterion survives the household editing
the recipe.

Evidence: ``signoff.json`` in the evidence dir::

    {
      "recipe": "Pizza",
      "timezone": "Europe/Berlin",
      "ui_language": "en",
      "step_durations_minutes": [15, 1440, 20],
      "unset": {
        "times_row_start": "Set",
        "step_starts": ["", "", ""]
      },
      "set": {
        "finish": "2026-08-23T12:00",
        "observed_at": "2026-08-13T09:00",
        "times_row_start": "Sat 11:25 (+9 d)",
        "step_starts": ["Sat 11:25 (+9 d)", "Sat 11:40 (+9 d)", "Sun 11:40 (+10 d)"]
      },
      "cleared": {
        "times_row_start": "Set",
        "step_starts": ["", "", ""]
      },
      "planner": {
        "meal_plan_from": "2026-08-23T12:00",
        "observed_at": "2026-08-13T09:15",
        "times_row_start": "Sat 11:25 (+9 d)"
      }
    }

(that example is a real chain, not a sketch: 20 minutes back from Sunday 12:00 is Sunday
11:40, 1440 before that is Saturday 11:40, and 15 before that is Saturday 11:25.)

``step_durations_minutes`` is each step's own time in step order, read from the step headers
(in minutes — convert what REQ-003 renders, so ``24 h`` is ``1440``). ``finish`` is the
weekday and time the tester chose, written as a local ISO datetime for the instance's zone.
``observed_at`` is the local wall clock at the moment the page was read — the start strings
are relative to *now*, so they cannot be graded without it. ``step_starts`` is the start
string beside each step header, in step order, empty string where a step shows none.
``times_row_start`` is the value in the fourth column of the times row.

The ``planner`` block is recorded after opening the recipe from the meal plan entry dialog's
recipe card, without the tester setting anything: ``meal_plan_from`` is that entry's date and
time, and ``times_row_start`` is what the times row showed on arrival.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

SHORT_WEEKDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')

#: any clock reading at all, used to prove the *absence* of absolute times
TIME_OF_DAY = re.compile(r'\d{1,2}:\d{2}')


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation."""
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    if not raw:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-004)')
    path = Path(raw) / name
    assert path.is_file(), f'required evidence {name} was not captured into {raw}'
    return path


def _normalized(value):
    """Collapse the whitespace a transcription picks up, so ' Sat  18:30 ' == 'Sat 18:30'."""
    return ' '.join(str(value).split())


def _local(value, zone):
    """Parse a transcribed local ISO datetime into an aware datetime in `zone`."""
    return datetime.fromisoformat(str(value)).replace(tzinfo=zone)


def _back_chain(finish, durations):
    """The start of every step, last step ending at `finish`.

    Deliberately a second implementation of the rule in vue3/src/utils/schedule_utils.ts
    rather than a call into it: a manual criterion graded against the very code it is
    checking would pass whatever that code happened to do.

    Durations are subtracted in UTC and converted back, because arithmetic on an aware
    datetime is wall-clock arithmetic in Python — a step spanning a DST boundary would
    otherwise come out an hour wrong, which is precisely the case this has to grade.
    """
    zone = finish.tzinfo
    starts = [None] * len(durations)

    start = finish
    for index in range(len(durations) - 1, -1, -1):
        minutes = durations[index]
        start = (start.astimezone(timezone.utc) - timedelta(minutes=max(minutes, 0))).astimezone(zone)
        starts[index] = start
    return starts


def _expected_start(start, reference):
    """The string the UI must show for `start` when read at `reference`.

    A second implementation of formatStartTime, for the same reason as above. The weekday
    table is spelled out rather than taken from strftime, whose %a follows the process
    locale and would make the grading depend on how the test host is configured.
    """
    time_of_day = start.strftime('%H:%M')
    day_offset = (start.date() - reference.date()).days

    if day_offset == 0:
        return f'Today {time_of_day}'
    if day_offset == 1:
        return f'Tomorrow {time_of_day}'

    weekday = f'{SHORT_WEEKDAYS[start.weekday()]} {time_of_day}'
    if abs(day_offset) <= 6:
        return weekday
    return f'{weekday} ({"+" if day_offset > 0 else "-"}{abs(day_offset)} d)'


def _assert_no_absolute_times(block, label):
    """PASS (a) and (c) — nothing on the page may read as a clock time."""
    times_row = _normalized(block.get('times_row_start', ''))
    assert times_row, f'{label}.times_row_start was not recorded — the times row column has to be transcribed either way'
    assert not TIME_OF_DAY.search(times_row), (f'AC5 FAIL — with no finish time set the times row still shows a time: {times_row!r}')

    for index, observed in enumerate(block.get('step_starts', [])):
        assert not _normalized(observed), (f'AC5 FAIL — {label}: step {index + 1} still shows a start time {_normalized(observed)!r} with no finish set')


def test_live_signoff():
    """PASS requires the whole chain, both empty states and the planner hand-off to hold."""
    data = json.loads(_require_evidence('signoff.json').read_text(encoding='utf-8'))

    assert _normalized(data.get('recipe', '')), 'signoff.json does not name the recipe that was observed'
    assert data.get('ui_language') == 'en', (
        'the observation has to be made with the interface in English; weekday names are rendered by the '
        'browser locale and cannot be graded otherwise'
    )

    zone = ZoneInfo(data['timezone'])
    durations = data.get('step_durations_minutes')
    assert isinstance(durations, list) and durations, 'step_durations_minutes missing — the chain cannot be recomputed without it'
    for minutes in durations:
        assert isinstance(minutes, int), f'step_durations_minutes must be whole minutes, got {minutes!r}'

    # A recipe whose every step is instantaneous would let a broken back-chain pass: every
    # start would legitimately equal the finish.
    assert max(durations) > 0, (f'the observed recipe has no step with a duration ({durations}) — it cannot show the chain this criterion is about')

    # (a) nothing absolute before a finish time is set
    _assert_no_absolute_times(data.get('unset', {}), 'unset')

    # (b) the chain, recomputed from the durations and the finish the tester recorded
    observed = data['set']
    finish = _local(observed['finish'], zone)
    reference = _local(observed['observed_at'], zone)
    starts = _back_chain(finish, durations)

    transcribed = observed.get('step_starts', [])
    assert len(transcribed) == len(durations), (f'{len(durations)} step durations were recorded but {len(transcribed)} start strings — '
                                                f'every step has to be transcribed')

    for index, (start, minutes) in enumerate(zip(starts, durations)):
        want = _expected_start(start, reference)
        got = _normalized(transcribed[index])
        assert got == want, (f'AC5 FAIL — step {index + 1} ({minutes} min) shows {got!r}, expected {want!r} '
                             f'for a finish of {observed["finish"]}')

    want_overall = _expected_start(starts[0], reference)
    got_overall = _normalized(observed.get('times_row_start', ''))
    assert got_overall == want_overall, (f'AC5 FAIL — the times row shows an overall start of {got_overall!r}, expected {want_overall!r}')

    # (c) clearing puts the page back exactly as it was
    _assert_no_absolute_times(data.get('cleared', {}), 'cleared')

    # (d) the planner hand-off arrives already scheduled, with the entry's own datetime
    planner = data['planner']
    planned_finish = _local(planner['meal_plan_from'], zone)
    planned_starts = _back_chain(planned_finish, durations)
    want_planned = _expected_start(planned_starts[0], _local(planner['observed_at'], zone))
    got_planned = _normalized(planner.get('times_row_start', ''))
    assert got_planned == want_planned, (
        f'AC5 FAIL — opened from the meal plan the times row shows {got_planned!r}, expected {want_planned!r} '
        f'for the planned meal at {planner["meal_plan_from"]}'
    )
