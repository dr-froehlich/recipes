"""Acceptance test for REQ-009 AC3 — the CI workflow actually ran, on PostgreSQL, and passed.

AC1 and AC2 (``test_ci_workflows.py``) prove the YAML is right. What this criterion checks is
that GitHub agreed: a workflow can be perfectly configured and still skip, and a skipped run
reports success. It is graded through the real entrypoint — the run GitHub recorded — rather
than from the configuration that produced it.

Graded by the System-Test phase (``steward validate REQ-009``) against evidence captured from
the run for the commit under validation. In an ordinary full-suite run there is no run to look
at and this skips; once the engine sets DEVSTEWARD_EVIDENCE_DIR — the only context in which
this test is named as an acceptance criterion — missing evidence is a hard failure, so it
cannot pass by finding nothing.

Evidence to capture into the evidence dir, for the head commit under validation::

    run.json          gh run view <id> --json conclusion,status,name,headSha,event,url
    steps.json        gh run view <id> --json jobs
    test-results.xml  the junit uploaded by the run's "Upload test results" step
                      (gh run download <id> -n test-results-3.12)

The load-bearing assertion is the junit one. A green run whose PostgreSQL tests skipped again
is precisely the failure this REQ exists to prevent, and from the run conclusion alone it is
indistinguishable from success. So the tests marked ``requires_postgres`` are discovered from
the source tree here — not hardcoded — and every one of them must appear in the junit as
executed, with no skip.
"""
import ast
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SEARCH_TESTS = REPO_ROOT / 'cookbook/tests/other'

# The marker whose tests had never executed anywhere before this REQ (REQ-001 Notes).
POSTGRES_MARKER = 'requires_postgres'
# What the REQ says that marker covers. A sanity check on discovery, not the assertion itself.
EXPECTED_POSTGRES_TESTS = 18

WORKFLOW_NAME = 'Continuous Integration'


def _require_evidence(name):
    """Return a captured evidence file, or skip when not running under a validation.

    The skip cannot launder a pass: once the evidence dir is set — the only context in which
    this test is named as an acceptance criterion — a missing artifact is an assertion
    failure, never a skip.
    """
    raw = os.environ.get('DEVSTEWARD_EVIDENCE_DIR')
    if not raw:
        pytest.skip('no DEVSTEWARD_EVIDENCE_DIR; graded by the System-Test phase (steward validate REQ-009)')
    path = Path(raw) / name
    assert path.is_file(), f'required evidence {name} was not captured into {raw}'
    return path


def _decorator_names(node):
    """Every dotted/plain name used as a decorator on a function or class."""
    names = []
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        while isinstance(target, ast.Attribute):
            target = target.value
        if isinstance(target, ast.Name):
            names.append(target.id)
    return names


def _discover_postgres_tests():
    """Find every test marked `requires_postgres`, as (classname, name) junit identities.

    Read out of the source rather than hardcoded, so the set cannot drift away from what the
    suite actually contains without this test noticing.
    """
    found = set()
    for path in sorted(SEARCH_TESTS.glob('test_*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        module = f'cookbook.tests.other.{path.stem}'

        def walk(node, prefix):
            for child in node.body:
                if isinstance(child, ast.ClassDef):
                    walk(child, f'{prefix}.{child.name}')
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if POSTGRES_MARKER in _decorator_names(child):
                        found.add((prefix, child.name))

        walk(tree, module)
    return found


def _testcases(junit_path):
    """Every <testcase> in a junit file, keyed by (classname, name)."""
    root = ET.parse(junit_path).getroot()
    cases = {}
    for case in root.iter('testcase'):
        cases[(case.get('classname', ''), case.get('name', ''))] = case
    return cases


def _all_steps(steps_blob):
    """Flatten `gh run view --json jobs` into a list of step dicts."""
    jobs = steps_blob.get('jobs', steps_blob) if isinstance(steps_blob, dict) else steps_blob
    steps = []
    for job in jobs:
        for step in job.get('steps', []):
            steps.append(step)
    return steps


def test_ci_run():
    """The run happened, concluded success, executed the PostgreSQL tests, and ran vitest."""
    run = json.loads(_require_evidence('run.json').read_text(encoding='utf-8'))

    # --- (a) the run happened at all, and passed --------------------------------------
    assert WORKFLOW_NAME.lower() in str(run.get('name', '')).lower(), (f'the captured run is {run.get("name")!r}, not the {WORKFLOW_NAME!r} workflow')
    assert run.get('status') == 'completed', f'the run has not finished: status={run.get("status")!r}'
    conclusion = run.get('conclusion')
    assert conclusion == 'success', (f'the {WORKFLOW_NAME} run concluded {conclusion!r}, not success — '
                                     f'{run.get("url", "no url captured")}')
    assert conclusion != 'skipped', 'the run skipped; a skipped run reports success and executes nothing'

    # --- (b) the PostgreSQL tests executed rather than skipping again ------------------
    expected = _discover_postgres_tests()
    assert len(expected) >= EXPECTED_POSTGRES_TESTS, (
        f'discovery found only {len(expected)} tests marked {POSTGRES_MARKER}, but REQ-009 names '
        f'{EXPECTED_POSTGRES_TESTS}; the discovery in this harness has drifted from the suite'
    )

    cases = _testcases(_require_evidence('test-results.xml'))
    assert cases, 'the captured junit contains no testcases at all'

    missing = sorted(f'{cls}::{name}' for cls, name in expected if (cls, name) not in cases)
    assert not missing, (f'{len(missing)} of the {len(expected)} {POSTGRES_MARKER} tests are absent from the run junit — they never '
                         f'ran:\n  ' + '\n  '.join(missing))

    skipped = sorted(f'{cls}::{name}' for cls, name in expected if cases[(cls, name)].find('skipped') is not None)
    assert not skipped, (
        f'{len(skipped)} of the {len(expected)} {POSTGRES_MARKER} tests skipped in CI, so the run is green only because '
        f'it did not test PostgreSQL:\n  ' + '\n  '.join(skipped)
    )

    # A test that errored out is not an executed pass either.
    broken = sorted(f'{cls}::{name}' for cls, name in expected if cases[(cls, name)].find('failure') is not None or cases[(cls, name)].find('error') is not None)
    assert not broken, f'{len(broken)} {POSTGRES_MARKER} tests did not pass:\n  ' + '\n  '.join(broken)

    # --- (c) the frontend suite ran ---------------------------------------------------
    steps = _all_steps(json.loads(_require_evidence('steps.json').read_text(encoding='utf-8')))
    assert steps, 'the captured step list is empty'

    vue_steps = [s for s in steps if 'vue' in str(s.get('name', '')).lower() and 'test' in str(s.get('name', '')).lower()]
    assert vue_steps, (f'no vitest step in the run\'s step list: {sorted(str(s.get("name")) for s in steps)}')
    for step in vue_steps:
        assert step.get('conclusion') == 'success', (
            f'the vitest step {step.get("name")!r} concluded {step.get("conclusion")!r}; '
            'a frontend suite that skipped is not a frontend suite that ran'
        )
