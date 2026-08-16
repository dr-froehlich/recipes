"""Derivation of a recipe's working and waiting totals from its steps (REQ-008).

Upstream keeps two unrelated clocks: ``Recipe.working_time``/``Recipe.waiting_time`` are
hand-entered and never computed, while ``Step.time`` is a bare duration nothing aggregates.
REQ-008 reconciles them without redefining either field's meaning. ``Step.time`` still means
*total elapsed* - which is what ``StepView``'s timer and REQ-004's bake schedule already assume
- and ``Step.working_time`` carves the attended portion out of it. Waiting is the remainder and
is never stored on a step.

A recipe's totals are **materialized**: as soon as its steps carry any elapsed time at all, the
recipe's own columns are overwritten with the sums, so every read path - the detail endpoint,
the 50-row list page, search, export - keeps reading plain columns and can never see a stale
number. While the steps total zero the columns stay exactly as hand-entered, which is what keeps
all 18 import paths working: no importer writes a step time, so an imported recipe behaves
precisely as it did before REQ-008.
"""
from django.db.models import Sum


def step_time_totals(recipe):
    """Return ``(elapsed, working, waiting)`` in minutes for a recipe's steps.

    One aggregate query. Sub-recipe steps contribute only their own two values - there is no
    recursion into ``Step.step_recipe``, matching REQ-004 Decision 7 so that the schedule and the
    totals cannot disagree about what a sub-recipe costs.
    """
    totals = recipe.steps.aggregate(elapsed=Sum('time'), working=Sum('working_time'))
    elapsed = totals['elapsed'] or 0
    working = totals['working'] or 0
    return elapsed, working, elapsed - working


def recipe_times_are_derived(recipe):
    """Whether this recipe's totals come from its steps rather than from a person.

    The switch is whether the steps carry any elapsed time at all. A recipe whose steps total
    zero keeps hand-editable totals; one whose steps total anything does not.
    """
    elapsed, _working, _waiting = step_time_totals(recipe)
    return elapsed > 0


def recalculate_recipe_times(recipe):
    """Materialize a recipe's totals from its steps. Returns whether they are derived.

    Writes through a queryset ``update()`` rather than ``instance.save()`` for two reasons: it
    fires no ``post_save`` on ``Recipe``, so it cannot re-enter the search-vector receiver, and it
    touches only the two columns, so it cannot clobber a concurrent write to an unrelated field
    from a stale instance. The write is skipped entirely when the values already match, which is
    the common case for a step save that changed only an instruction.
    """
    from cookbook.models import Recipe

    elapsed, working, waiting = step_time_totals(recipe)
    if elapsed <= 0:
        return False

    if recipe.working_time != working or recipe.waiting_time != waiting:
        Recipe.objects.filter(pk=recipe.pk).update(working_time=working, waiting_time=waiting)
        recipe.working_time = working
        recipe.waiting_time = waiting
    return True


def recalculate_recipe_times_by_id(recipe_ids):
    """Materialize totals for the given recipe ids, tolerating ids that no longer exist."""
    from cookbook.models import Recipe

    for recipe in Recipe.objects.filter(pk__in=list(recipe_ids)):
        recalculate_recipe_times(recipe)
