"""Acceptance test for REQ-008 AC1 — recipe totals are materialized from the steps.

`Step.time` still means total elapsed; `Step.working_time` is the attended portion inside it.
As soon as a recipe's steps carry any elapsed time at all, the recipe's own `working_time` and
`waiting_time` columns are overwritten with the sums, on every write path there is. While the
steps total zero the columns stay exactly as hand-entered — which is what keeps all 18 import
paths working, since no importer writes a step time.
"""
import json

import pytest
from django.contrib import auth
from django.urls import reverse
from django_scopes import scopes_disabled

from cookbook.helper.recipe_time_helper import (recalculate_recipe_times, recipe_times_are_derived,
                                                step_time_totals)
from cookbook.models import Recipe, Step

RECIPE_DETAIL_URL = 'api:recipe-detail'


def make_recipe(space, user, working_time=15, waiting_time=25):
    """A recipe with hand-entered totals and no steps yet."""
    return Recipe.objects.create(
        name='timed recipe', working_time=working_time, waiting_time=waiting_time,
        created_by=user, space=space, internal=True,
    )


def make_step(space, time=0, working_time=0, name='step'):
    return Step.objects.create(name=name, instruction='', time=time, working_time=working_time, space=space)


def reload(recipe):
    return Recipe.objects.get(pk=recipe.pk)


def test_step_save_materializes_totals(space_1, u1_s1):
    """Saving a step with a non-zero time rewrites the owning recipe's two columns."""
    with scopes_disabled():
        recipe = make_recipe(space_1, auth.get_user(u1_s1))
        step = make_step(space_1, time=70, working_time=10)
        recipe.steps.add(step)

        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (10, 60)

        # a later edit of the same step flows through too
        step.time = 100
        step.working_time = 25
        step.save()

        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (25, 75)


def test_totals_are_the_sums_across_all_steps(space_1, u1_s1):
    with scopes_disabled():
        recipe = make_recipe(space_1, auth.get_user(u1_s1))
        recipe.steps.add(make_step(space_1, time=70, working_time=10, name='knead then ferment'))
        recipe.steps.add(make_step(space_1, time=45, working_time=45, name='shape'))
        recipe.steps.add(make_step(space_1, time=720, working_time=0, name='cold proof'))

        assert step_time_totals(recipe) == (835, 55, 780)
        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (55, 780)


def test_step_delete_recomputes_the_remaining_steps(space_1, u1_s1):
    """post_delete cannot ask the step which recipes owned it — pre_delete stashes them."""
    with scopes_disabled():
        recipe = make_recipe(space_1, auth.get_user(u1_s1))
        keeper = make_step(space_1, time=70, working_time=10)
        doomed = make_step(space_1, time=200, working_time=50)
        recipe.steps.add(keeper)
        recipe.steps.add(doomed)

        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (60, 210)

        doomed.delete()

        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (10, 60)


def test_removing_and_clearing_steps_recomputes(space_1, u1_s1):
    with scopes_disabled():
        recipe = make_recipe(space_1, auth.get_user(u1_s1))
        first = make_step(space_1, time=70, working_time=10)
        second = make_step(space_1, time=30, working_time=30)
        recipe.steps.add(first, second)

        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (40, 60)

        recipe.steps.remove(second)

        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (10, 60)

        # clearing every step drops the recipe back below the threshold, so the last derived
        # values simply stand — there is nothing left to derive from
        recipe.steps.clear()

        assert recipe_times_are_derived(reload(recipe)) is False
        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (10, 60)


def test_untimed_steps_leave_the_curated_totals_alone(space_1, u1_s1):
    """The whole imported collection lives in this branch: steps exist, none of them timed."""
    with scopes_disabled():
        recipe = make_recipe(space_1, auth.get_user(u1_s1), working_time=15, waiting_time=25)
        step = make_step(space_1, time=0, working_time=0)
        recipe.steps.add(step)

        assert recipe_times_are_derived(recipe) is False
        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (15, 25)

        # an unrelated edit to the step must not disturb them either
        step.instruction = 'stir'
        step.save()

        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (15, 25)


def test_a_step_shared_by_two_recipes_updates_both(space_1, u1_s1):
    """Recipe.steps is a ManyToMany, so recipe_set may hold more than one recipe."""
    with scopes_disabled():
        user = auth.get_user(u1_s1)
        first = make_recipe(space_1, user)
        second = make_recipe(space_1, user)
        shared = make_step(space_1, time=90, working_time=20)
        first.steps.add(shared)
        second.steps.add(shared)

        shared.time = 120
        shared.working_time = 30
        shared.save()

        assert (reload(first).working_time, reload(first).waiting_time) == (30, 90)
        assert (reload(second).working_time, reload(second).waiting_time) == (30, 90)


def test_sub_recipe_steps_are_not_recursed_into(space_1, u1_s1):
    """A step pointing at a sub-recipe contributes only its own two values (REQ-004 Decision 7)."""
    with scopes_disabled():
        user = auth.get_user(u1_s1)
        levain = make_recipe(space_1, user)
        levain.steps.add(make_step(space_1, time=720, working_time=15))

        parent = make_recipe(space_1, user)
        pointer = make_step(space_1, time=30, working_time=5, name='build the levain')
        pointer.step_recipe = levain
        pointer.save()
        parent.steps.add(pointer)

        # 30/5 from the pointer alone — the sub-recipe's 720 is not counted
        assert step_time_totals(parent) == (30, 5, 25)
        assert (reload(parent).working_time, reload(parent).waiting_time) == (5, 25)


def test_nested_recipe_write_materializes(u1_s1, space_1):
    """The recipe editor writes its steps nested inside the recipe payload."""
    with scopes_disabled():
        recipe = make_recipe(space_1, auth.get_user(u1_s1))
        recipe.steps.add(make_step(space_1, time=0, working_time=0))

    payload = json.loads(u1_s1.get(reverse(RECIPE_DETAIL_URL, args={recipe.pk})).content)
    payload['steps'][0]['time'] = 200
    payload['steps'][0]['working_time'] = 20

    response = u1_s1.put(
        reverse(RECIPE_DETAIL_URL, args={recipe.pk}), json.dumps(payload), content_type='application/json'
    )
    assert response.status_code == 200

    with scopes_disabled():
        assert (reload(recipe).working_time, reload(recipe).waiting_time) == (20, 180)


def test_the_backfill_mechanism(space_1, u1_s1):
    """The same recalculation the migration runs across the existing collection.

    Every pre-REQ-008 step has working_time 0, so a timed recipe materializes to working 0 and
    waiting equal to its elapsed total — replacing whatever was curated. That is the accepted
    loss the REQ records; what must not happen is an untimed recipe being touched.
    """
    with scopes_disabled():
        user = auth.get_user(u1_s1)

        legacy_timed = make_recipe(space_1, user, working_time=45, waiting_time=2400)
        legacy_timed.steps.add(make_step(space_1, time=1440, working_time=0))

        untimed = make_recipe(space_1, user, working_time=15, waiting_time=25)
        untimed.steps.add(make_step(space_1, time=0, working_time=0))

        # simulate the pre-migration state: totals as curated, steps already timed
        Recipe.objects.filter(pk=legacy_timed.pk).update(working_time=45, waiting_time=2400)

        assert recalculate_recipe_times(reload(legacy_timed)) is True
        assert recalculate_recipe_times(reload(untimed)) is False

        assert (reload(legacy_timed).working_time, reload(legacy_timed).waiting_time) == (0, 1440)
        assert (reload(untimed).working_time, reload(untimed).waiting_time) == (15, 25)


@pytest.mark.parametrize('time,working,expected', [
    (0, 0, (0, 0, 0)),
    (60, 0, (60, 0, 60)),
    (60, 60, (60, 60, 0)),
    (70, 10, (70, 10, 60)),
])
def test_step_time_totals_arithmetic(space_1, u1_s1, time, working, expected):
    with scopes_disabled():
        recipe = make_recipe(space_1, auth.get_user(u1_s1))
        recipe.steps.add(make_step(space_1, time=time, working_time=working))
        assert step_time_totals(recipe) == expected
