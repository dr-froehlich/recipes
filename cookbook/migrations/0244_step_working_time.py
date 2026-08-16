"""Add Step.working_time and materialize every recipe's totals from its steps (REQ-008).

The forward backfill is deliberately lossy and there is no way to make it otherwise. Every
existing step has ``working_time`` 0 - the field is new - so a recipe whose steps carry elapsed
time materializes to working 0 and waiting equal to that elapsed total, replacing whatever a
person or an importer had typed. A recipe with a curated waiting time of 2400 whose steps
currently sum to 1440 ends up at 1440, and the 2400 is gone rather than shadowed.

That is the requirement, not an accident: REQ-008 Decision 5 says the steps win as soon as they
carry any time, and the REQ's "Accepted data loss" note owns the consequence. Recipes whose steps
have no times at all are left completely alone, which is every recipe any importer has ever
produced.

The reverse drops the column but cannot restore the superseded totals, because nothing records
them. Reversing therefore leaves the derived values in place as though they had been typed.
"""
from django.db import migrations, models
from django_scopes import scopes_disabled


def materialize_recipe_times(apps, schema_editor):
    """Write derived totals onto every recipe whose steps carry elapsed time."""
    Recipe = apps.get_model('cookbook', 'Recipe')

    with scopes_disabled():
        for recipe in Recipe.objects.all().prefetch_related('steps').iterator(chunk_size=200):
            elapsed = sum((step.time or 0) for step in recipe.steps.all())
            if elapsed <= 0:
                continue
            working = sum((step.working_time or 0) for step in recipe.steps.all())
            waiting = elapsed - working
            if recipe.working_time != working or recipe.waiting_time != waiting:
                Recipe.objects.filter(pk=recipe.pk).update(working_time=working, waiting_time=waiting)


def noop_reverse(apps, schema_editor):
    """Nothing to undo - the superseded totals were never recorded anywhere."""


class Migration(migrations.Migration):

    dependencies = [
        ('cookbook', '0243_userpreference_use_readable_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='step',
            name='working_time',
            field=models.IntegerField(blank=True, default=0),
        ),
        migrations.RunPython(materialize_recipe_times, noop_reverse),
    ]
