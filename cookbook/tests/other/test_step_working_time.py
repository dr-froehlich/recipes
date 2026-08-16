"""Acceptance test for REQ-008 AC3 — a step's working time can never exceed its elapsed time.

`working_time` is carved out of `time`, so a step claiming more attended minutes than it lasts
would push the waiting portion — and therefore every recipe total derived from it — negative.
The rule is enforced on every path a value can arrive by: the step endpoint, a nested recipe
write, and the model's own `clean()` for the admin and anything calling `full_clean()`.
"""
import json

import pytest
from django.contrib import auth
from django.core.exceptions import ValidationError
from django.urls import reverse
from django_scopes import scopes_disabled

from cookbook.models import Recipe, Step

STEP_LIST_URL = 'api:step-list'
STEP_DETAIL_URL = 'api:step-detail'
RECIPE_DETAIL_URL = 'api:recipe-detail'


def test_step_endpoint_rejects_working_time_above_time(u1_s1, recipe_1_s1):
    with scopes_disabled():
        step = recipe_1_s1.steps.first()

    r = u1_s1.patch(
        reverse(STEP_DETAIL_URL, args={step.id}),
        {'time': 60, 'working_time': 61},
        content_type='application/json'
    )
    assert r.status_code == 400
    assert 'working_time' in json.loads(r.content)


def test_step_endpoint_checks_a_partial_write_against_the_stored_half(u1_s1, recipe_1_s1):
    """A PATCH setting only working_time is still graded against the stored time."""
    with scopes_disabled():
        step = recipe_1_s1.steps.first()
        step.time = 40
        step.working_time = 0
        step.save()

    too_much = u1_s1.patch(
        reverse(STEP_DETAIL_URL, args={step.id}), {'working_time': 41}, content_type='application/json'
    )
    assert too_much.status_code == 400

    allowed = u1_s1.patch(
        reverse(STEP_DETAIL_URL, args={step.id}), {'working_time': 40}, content_type='application/json'
    )
    assert allowed.status_code == 200
    assert json.loads(allowed.content)['working_time'] == 40


@pytest.mark.parametrize('time,working_time', [(60, 0), (60, 60), (60, 25), (0, 0)])
def test_step_endpoint_accepts_valid_pairs(u1_s1, recipe_1_s1, time, working_time):
    with scopes_disabled():
        step = recipe_1_s1.steps.first()

    r = u1_s1.patch(
        reverse(STEP_DETAIL_URL, args={step.id}),
        {'time': time, 'working_time': working_time},
        content_type='application/json'
    )
    assert r.status_code == 200
    response = json.loads(r.content)
    assert (response['time'], response['working_time']) == (time, working_time)


def test_nested_recipe_write_rejects_working_time_above_time(u1_s1, recipe_1_s1):
    payload = json.loads(u1_s1.get(reverse(RECIPE_DETAIL_URL, args={recipe_1_s1.pk})).content)
    payload['steps'][0]['time'] = 30
    payload['steps'][0]['working_time'] = 31

    r = u1_s1.put(
        reverse(RECIPE_DETAIL_URL, args={recipe_1_s1.pk}), json.dumps(payload), content_type='application/json'
    )
    assert r.status_code == 400


def test_model_clean_rejects_working_time_above_time(space_1):
    with scopes_disabled():
        step = Step.objects.create(name='over', instruction='', time=10, working_time=30, space=space_1)
        with pytest.raises(ValidationError) as error:
            step.clean()
        assert 'working_time' in error.value.message_dict

        step.working_time = 10
        step.clean()  # equal is fine


def test_working_time_defaults_to_zero(space_1, u1_s1):
    """A step written with no working time at all is fully unattended — which is what every
    step in the collection was before REQ-008 existed."""
    with scopes_disabled():
        step = Step.objects.create(name='legacy', instruction='', time=720, space=space_1)
        assert step.working_time == 0

        recipe = Recipe.objects.create(
            name='legacy recipe', created_by=auth.get_user(u1_s1), space=space_1, internal=True
        )
        recipe.steps.add(step)
        recipe.refresh_from_db()
        assert (recipe.working_time, recipe.waiting_time) == (0, 720)


def test_step_endpoint_creates_with_working_time(u1_s1):
    r = u1_s1.post(
        reverse(STEP_LIST_URL),
        {'instruction': 'knead then rest', 'ingredients': [], 'time': 70, 'working_time': 10},
        content_type='application/json'
    )
    assert r.status_code == 201
    response = json.loads(r.content)
    assert (response['time'], response['working_time']) == (70, 10)


def test_existing_step_reads_back_unchanged(u1_s1, recipe_1_s1):
    """REQ-008 is additive: a step nobody has touched keeps its time and reports no work."""
    with scopes_disabled():
        step = recipe_1_s1.steps.first()
        original_time = step.time

    response = json.loads(u1_s1.get(reverse(STEP_DETAIL_URL, args={step.id})).content)
    assert response['time'] == original_time
    assert response['working_time'] == 0
