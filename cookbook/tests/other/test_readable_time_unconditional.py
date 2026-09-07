"""Acceptance test for REQ-010 AC1 — the readable-time preference is gone from every layer.

Removing a per-user preference is a seven-place change, and six of those places fail *silently*
when they are missed. A leftover model field keeps a dead column alive through every future
migration; a leftover serializer entry keeps serving it to clients; a leftover checkbox binds
``v-model`` to a property the API no longer returns, which Vue renders as a permanently
unchecked box that silently does nothing; leftover ``useReadableTime`` in the generated client
means the next regeneration produces a diff nobody asked for; and a leftover parameter on
``formatDuration`` is the toggle growing back as a default argument.

None of that shows up in a passing test suite, which is why this one reads all seven at once —
the Python side through the model and serializer, the frontend side through the source files,
since there is no runtime that can be asked.

Migration *state* consistency is not re-checked here: ``test_baseline.py::test_no_missing_migrations``
(REQ-001 AC1) already fails the gate on any model change carrying no migration. What this module
adds is that the migration actually **removes** the field rather than merely existing.
"""
import re
from pathlib import Path

from cookbook.models import UserPreference
from cookbook.serializer import UserPreferenceSerializer

REPO_ROOT = Path(__file__).resolve().parents[3]

API_FIELD = 'use_readable_time'
CLIENT_PROPERTY = 'useReadableTime'
LOCALE_KEYS = ('Use_Readable_Time', 'Use_Readable_Time_Help')


def test_preference_is_gone():
    """No layer still carries the preference, and the formatter takes no preference argument."""
    # 1. the model — the field, and a migration that actually drops the column
    field_names = {field.name for field in UserPreference._meta.get_fields()}
    assert API_FIELD not in field_names, (
        f'UserPreference still declares {API_FIELD}; readable durations are unconditional '
        f'(REQ-010 Decision 3)'
    )

    migrations = (REPO_ROOT / 'cookbook/migrations').glob('*.py')
    removals = [
        path for path in migrations
        if 'RemoveField' in (source := path.read_text(encoding='utf-8'))
        and f"name='{API_FIELD}'" in source
    ]
    assert removals, (
        f'no migration removes {API_FIELD} — the column would survive on every existing '
        f'deployment even though the model no longer knows about it'
    )

    # 2. the API — a field the serializer still lists is still served
    assert API_FIELD not in UserPreferenceSerializer.Meta.fields, (
        f'{API_FIELD} is still served by UserPreferenceSerializer'
    )

    # 3. the generated client — a stale property here becomes surprise churn on the next
    # regeneration, and lets frontend code go on reading a preference that cannot arrive
    for model in ('UserPreference.ts', 'PatchedUserPreference.ts'):
        source = (REPO_ROOT / 'vue3/src/openapi/models' / model).read_text(encoding='utf-8')
        assert CLIENT_PROPERTY not in source, f'generated client model {model} still types {CLIENT_PROPERTY}'
        assert API_FIELD not in source, f'generated client model {model} still maps {API_FIELD}'

    # 4. the settings page — a checkbox bound to a property the API no longer returns renders
    # as an unchecked box that saves nothing, which is worse than no checkbox at all
    settings = (REPO_ROOT / 'vue3/src/components/settings/CosmeticSettings.vue').read_text(encoding='utf-8')
    assert CLIENT_PROPERTY not in settings, 'Cosmetic settings still offers the readable-time checkbox'

    # 5. the English catalog — the two keys go, the hour unit stays (it is what the formatter
    # renders with, and the one key the pull request still offers upstream)
    catalog = (REPO_ROOT / 'vue3/src/locales/en.json').read_text(encoding='utf-8')
    for key in LOCALE_KEYS:
        assert f'"{key}"' not in catalog, f'en.json still carries the {key} string'
    assert '"h":' in catalog, 'en.json lost the hour unit key the formatter renders with'

    # 6. the formatter — one required parameter and one optional label bag; a preference
    # argument, even defaulted, is the toggle growing back
    formatter = (REPO_ROOT / 'vue3/src/utils/duration_utils.ts').read_text(encoding='utf-8')
    assert CLIENT_PROPERTY not in formatter, 'duration_utils.ts still takes a preference argument'
    signature = re.search(r'export function formatDuration\((.*?)\): string', formatter, re.S)
    assert signature, 'formatDuration is no longer declared as expected in duration_utils.ts'
    parameters = [part for part in signature.group(1).split(',') if ':' in part]
    assert len(parameters) == 2, (
        f'formatDuration should take exactly (minutes, labels); found {len(parameters)} '
        f'parameters in {signature.group(1)!r}'
    )

    # 7. the composable — it binds i18n labels and nothing else; still reading the preference
    # store would mean the display path depends on a field that no longer arrives
    composable = (REPO_ROOT / 'vue3/src/composables/useDurationDisplay.ts').read_text(encoding='utf-8')
    assert 'UserPreferenceStore' not in composable, (
        'useDurationDisplay still reads the user-preference store'
    )
