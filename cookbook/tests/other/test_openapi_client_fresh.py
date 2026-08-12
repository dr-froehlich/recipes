"""Acceptance test for REQ-003 AC3 — the generated API client is not stale.

``vue3/src/openapi/`` is generated from the live schema by ``scripts/generate_api_client.py``
and must never be hand-edited. Nothing else in the repository notices when a serializer grows
a field and the client is not regenerated: the backend stays green, the frontend simply
cannot see the field and the feature silently does nothing.

This test closes that hole for the one field REQ-003 adds. It reads the serializer's own
field list, so it fails both ways round — if ``use_readable_time`` is dropped from the API,
and if the generated client is missing it.

Note for whoever regenerates next: the committed client was generated on a checkout that had
the enterprise and open-data plugins installed. Running the generator without them strips
every plugin model and roughly two thirds of ``apis/ApiApi.ts``. Regenerate, then keep only
the model files your change actually touched (plan 0003).
"""
from pathlib import Path

from cookbook.serializer import UserPreferenceSerializer

REPO_ROOT = Path(__file__).resolve().parents[3]
CLIENT_MODELS = REPO_ROOT / 'vue3/src/openapi/models'

# the API field REQ-003 adds, and the property name the typescript-fetch generator gives it
API_FIELD = 'use_readable_time'
CLIENT_PROPERTY = 'useReadableTime'


def test_user_preference_exposes_readable_time():
    """The preference is served by the API and typed in the generated client, both ways."""
    assert API_FIELD in UserPreferenceSerializer.Meta.fields, (
        f'{API_FIELD} is not served by UserPreferenceSerializer — the frontend cannot read it'
    )

    # UserPreference is the GET/PUT model, PatchedUserPreference the one a PATCH writes
    # through; a client missing either half cannot round-trip the preference.
    for model in ('UserPreference.ts', 'PatchedUserPreference.ts'):
        path = CLIENT_MODELS / model
        assert path.is_file(), f'generated client model {model} is missing'
        source = path.read_text(encoding='utf-8')

        assert f'{CLIENT_PROPERTY}?: boolean;' in source, (
            f'{model} has no {CLIENT_PROPERTY} property — the client is stale, '
            f'regenerate it with scripts/generate_api_client.py'
        )
        assert f"'{CLIENT_PROPERTY}': json['{API_FIELD}']" in source, (
            f'{model} does not read {API_FIELD} from a response'
        )
        assert f"'{API_FIELD}': value['{CLIENT_PROPERTY}']" in source, (
            f'{model} does not send {API_FIELD} back to the server'
        )
