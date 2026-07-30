"""Baseline check for REQ-001 — the project builds.

REQ-001's criterion is that the project builds and its suite passes from a clean
checkout. The "suite passes" half is enforced on every land by the engine's configured
full-suite run, which tolerates the environment-conditional skips (see REQ-001's Notes).
The "builds" half is what this module names.

A stricter `manage.py check` is deliberately *not* asserted here: `recipes/test_settings`
uninstalls `django.contrib.messages` and friends on purpose, which raises admin.E406
under the test settings only, and the vite manifest is absent until `yarn build` has run.
Both are artifacts of the test environment rather than statements about the project, so
asserting on them would make this a test of the settings module instead of a baseline.

What remains is the check that earns its keep as soon as a REQ touches a model: a field
added without a migration passes every API test and then breaks the deploy.
"""

import pytest
from django.core.management import call_command


def test_no_missing_migrations():
    """Every model change has a migration — `makemigrations --check` finds nothing to do."""
    try:
        call_command('makemigrations', '--check', '--dry-run', verbosity=0)
    except SystemExit:
        pytest.fail(
            'Model changes exist with no corresponding migration. '
            'Run `python manage.py makemigrations` and commit the result.'
        )
