"""Acceptance tests for REQ-003 — the readable-time user preference.

Kept in a fork-local module rather than added to upstream's ``test_api_userpreference.py``
so that the fork's own coverage never collides with upstream's file on a rebase
(REQ-001 Decision 2).
"""
import json

import pytest
from django.contrib import auth
from django.urls import reverse
from django_scopes import scopes_disabled

from cookbook.models import UserPreference

DETAIL_URL = 'api:userpreference-detail'


def test_readable_time_defaults_on(u1_s1):
    """A freshly created preference has readable times enabled (REQ-003 Decision 3)."""
    user = auth.get_user(u1_s1)

    with scopes_disabled():
        UserPreference.objects.filter(user=user).delete()
        preference = UserPreference.objects.create(user=user)

    assert preference.use_readable_time is True

    with scopes_disabled():
        assert UserPreference.objects.get(user=user).use_readable_time is True


def test_readable_time_round_trips_through_the_api(u1_s1):
    """The preference is readable and writable through the user-preference endpoint."""
    user = auth.get_user(u1_s1)

    r = u1_s1.get(reverse(DETAIL_URL, args={user.id}))
    assert r.status_code == 200
    assert json.loads(r.content)['use_readable_time'] is True

    r = u1_s1.patch(
        reverse(DETAIL_URL, args={user.id}),
        {'use_readable_time': False},
        content_type='application/json'
    )
    assert r.status_code == 200
    assert json.loads(r.content)['use_readable_time'] is False

    # the write is persisted, not merely echoed back
    r = u1_s1.get(reverse(DETAIL_URL, args={user.id}))
    assert json.loads(r.content)['use_readable_time'] is False

    with scopes_disabled():
        assert UserPreference.objects.get(user=user).use_readable_time is False


@pytest.mark.parametrize("value", [True, False])
def test_readable_time_is_per_user(value, u1_s1, u2_s1):
    """One user's choice does not move another user's preference."""
    user = auth.get_user(u1_s1)
    other = auth.get_user(u2_s1)

    r = u1_s1.patch(
        reverse(DETAIL_URL, args={user.id}),
        {'use_readable_time': value},
        content_type='application/json'
    )
    assert r.status_code == 200

    with scopes_disabled():
        assert UserPreference.objects.get(user=other).use_readable_time is True
