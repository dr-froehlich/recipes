"""Acceptance test for REQ-008 AC2 — the derived-times lock.

While a recipe's steps total zero elapsed minutes its `working_time` and `waiting_time` behave
exactly as they always have: stored, hand-editable, written by every importer. The moment the
steps carry any time the totals come from them and a person may no longer type a contradicting
value.

The lock rejects on the two paths a person types into — a recipe update and the batch endpoint —
and deliberately does not reject on create or on the export serializer, where a payload carries
the totals and the steps together and materialization simply wins. Rejecting there would break
Tandoor's own export round trip and every importer that writes the recipe pair.

The rejection is keyed on the submitted value *differing* from the derived one: the recipe editor
PATCHes the whole object, so a derived recipe resubmits its derived totals on every save, and
rejecting their mere presence would make such a recipe unsavable.
"""
import json

from django.contrib import auth
from django.urls import reverse
from django_scopes import scopes_disabled

from cookbook.models import Recipe, Step
from cookbook.serializer import RecipeExportSerializer

DETAIL_URL = 'api:recipe-detail'
LIST_URL = 'api:recipe-list'
BATCH_URL = 'api:recipe-batch-update'


def make_recipe(space, user, working_time=15, waiting_time=25):
    return Recipe.objects.create(
        name='lock subject', working_time=working_time, waiting_time=waiting_time,
        created_by=user, space=space, internal=True,
    )


def make_step(space, time=0, working_time=0):
    return Step.objects.create(name='s', instruction='', time=time, working_time=working_time, space=space)


def derived_recipe(space, user):
    """A recipe whose steps total 70 elapsed / 10 working, so its totals are derived 10 / 60."""
    with scopes_disabled():
        recipe = make_recipe(space, user)
        recipe.steps.add(make_step(space, time=70, working_time=10))
        recipe.refresh_from_db()
    return recipe


def manual_recipe(space, user):
    """A recipe with steps but no step times — the shape every importer produces."""
    with scopes_disabled():
        recipe = make_recipe(space, user)
        recipe.steps.add(make_step(space, time=0, working_time=0))
        recipe.refresh_from_db()
    return recipe


def reload(recipe):
    with scopes_disabled():
        return Recipe.objects.get(pk=recipe.pk)


def test_patch_with_a_different_total_is_rejected(u1_s1, space_1):
    recipe = derived_recipe(space_1, auth.get_user(u1_s1))

    r = u1_s1.patch(
        reverse(DETAIL_URL, args={recipe.pk}), {'working_time': 999}, content_type='application/json'
    )
    assert r.status_code == 400
    assert 'working_time' in json.loads(r.content)
    assert (reload(recipe).working_time, reload(recipe).waiting_time) == (10, 60)

    r = u1_s1.patch(
        reverse(DETAIL_URL, args={recipe.pk}), {'waiting_time': 999}, content_type='application/json'
    )
    assert r.status_code == 400
    assert 'waiting_time' in json.loads(r.content)


def test_patch_resubmitting_the_derived_totals_is_accepted(u1_s1, space_1):
    """The editor sends the whole object back; a no-op must not be an error."""
    recipe = derived_recipe(space_1, auth.get_user(u1_s1))

    r = u1_s1.patch(
        reverse(DETAIL_URL, args={recipe.pk}),
        {'name': 'renamed', 'working_time': 10, 'waiting_time': 60},
        content_type='application/json'
    )
    assert r.status_code == 200
    assert reload(recipe).name == 'renamed'
    assert (reload(recipe).working_time, reload(recipe).waiting_time) == (10, 60)


def test_patch_on_an_untimed_recipe_still_works(u1_s1, space_1):
    recipe = manual_recipe(space_1, auth.get_user(u1_s1))

    r = u1_s1.patch(
        reverse(DETAIL_URL, args={recipe.pk}),
        {'working_time': 45, 'waiting_time': 2400},
        content_type='application/json'
    )
    assert r.status_code == 200
    assert (reload(recipe).working_time, reload(recipe).waiting_time) == (45, 2400)


def test_batch_update_skips_derived_recipes(u1_s1, space_1):
    """A bulk update() bypasses every save hook, so the lock is applied in the view by hand."""
    user = auth.get_user(u1_s1)
    locked = derived_recipe(space_1, user)
    editable = manual_recipe(space_1, user)

    r = u1_s1.put(
        reverse(BATCH_URL),
        {'recipes': [locked.pk, editable.pk], 'working_time': 5, 'waiting_time': 7},
        content_type='application/json'
    )
    assert r.status_code == 200

    assert (reload(locked).working_time, reload(locked).waiting_time) == (10, 60)
    assert (reload(editable).working_time, reload(editable).waiting_time) == (5, 7)


def test_create_with_timed_steps_ends_derived(u1_s1):
    """Creation is never rejected — materialization overwrites whatever was submitted."""
    payload = {
        'name': 'created with steps',
        'working_time': 999,
        'waiting_time': 999,
        'steps': [
            {'instruction': 'knead then ferment', 'ingredients': [], 'time': 70, 'working_time': 10},
            {'instruction': 'bake', 'ingredients': [], 'time': 45, 'working_time': 5},
        ],
    }

    r = u1_s1.post(reverse(LIST_URL), json.dumps(payload), content_type='application/json')
    assert r.status_code == 201

    with scopes_disabled():
        recipe = Recipe.objects.get(pk=json.loads(r.content)['id'])
    assert (recipe.working_time, recipe.waiting_time) == (15, 100)


def test_export_round_trip_is_accepted_and_ends_derived(u1_s1, space_1):
    """A Tandoor export payload carries both the totals and the step times; it must import."""
    recipe = derived_recipe(space_1, auth.get_user(u1_s1))

    with scopes_disabled():
        exported = RecipeExportSerializer(recipe).data
        assert exported['steps'][0]['working_time'] == 10
        assert (exported['working_time'], exported['waiting_time']) == (10, 60)

    request = u1_s1.get(reverse(DETAIL_URL, args={recipe.pk})).wsgi_request
    with scopes_disabled():
        imported = RecipeExportSerializer(data=json.loads(json.dumps(exported)), context={'request': request})
        assert imported.is_valid(), imported.errors
        created = imported.save()
        created.refresh_from_db()

    assert (created.working_time, created.waiting_time) == (10, 60)
