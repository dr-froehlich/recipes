# Plan 0001 — REQ-001's develop checkpoint: an executable green baseline

> Authored 2026-07-30. A plan is a thinking document: how a chunk of work will be
> approached, the alternatives weighed, the sequence. It is not a contract (REQs are).

## Context

Advances [REQ-001](../../requirements/REQ-001.md), the frozen north star, whose develop
step is the first eligible step in this project's ledger and which
[REQ-002](../../requirements/REQ-002.md) and [REQ-003](../../requirements/REQ-003.md)
both depend on.

REQ-001 is a `kind: spec` REQ. It specifies no behaviour to build — its single acceptance
criterion is that *the project builds and its test suite passes from a clean checkout*.
So this checkpoint's product is not code: it is an **observed** green baseline for the
fork, recorded before REQ-002 starts changing CI and REQ-002/REQ-003 start changing the
image and the schema. The value of doing it now rather than dropping the dependency is
precisely that: the first time a land gate runs the suite should not also be the first
time anyone has looked at it.

One defect has to be fixed to get there. REQ-001's AC1 command, written at onboarding, is:

```
PYTEST_ADDOPTS="--no-cov" python -m pytest
```

That command cannot execute in this project's gate, for two compounding reasons that
`.devsteward/config.yaml` already documents:

1. The engine rebinds only a **leading** `python` token to `verify.python`
   (`.venv/bin/python`). Here the leading token is the env-var assignment, so no rebinding
   happens.
2. This workstation has no ambient `python` at all — only `python3`. So the unrebound
   `python` is not merely the wrong interpreter, it does not exist.

The AC would therefore red on "command not found" rather than on anything about the
project. That is not a weakening of the north star to be superseded — the *requirement*
is unchanged; only its inexecutable spelling is corrected.

## Approach

The first attempt was simply to fix the spelling to `python -m pytest --no-cov` — the
project's configured `verify.full_suite`, with a leading `python` the engine can rebind
and `--no-cov` as a CLI flag beating the `--cov=.` that `pytest.ini` hardcodes into
`addopts`. That runs, and it is green: **1254 passed, 18 skipped in 53 s**.

The gate rejected it anyway, and was right to:

```
18 skipped of 1272 — a skip cannot satisfy a land gate (skip ≠ green)
```

A *named* acceptance test may not skip. The suite legitimately skips 18 tests — every one
of them `requires PostgreSQL`, because the suite defaults to SQLite. So naming the whole
suite as a criterion is self-defeating: the criterion can only ever be satisfied by an
environment that this project deliberately does not require. The two rules are not in
conflict, they are addressed at different things — `full_suite` tolerates skips *because*
it is the blanket run, and named ACs may not *because* they are supposed to name a
behaviour that observably executed.

So the redundancy has to go, and the right half to keep is the one `full_suite` does not
already cover. "The suite passes" is enforced at every land, for every REQ, by
`verify.full_suite` — restating it as AC1 adds nothing. "The project builds" is not
covered by anything. AC1 becomes that: a `cookbook/tests/other/test_baseline.py` asserting
Django's migration state is consistent with the models. It always runs, never skips, and
is genuinely disconfirmable — a model field added without a migration passes every API
test in the suite and then breaks the deploy, which is exactly the failure REQ-003 is
positioned to cause.

A stricter `manage.py check` was tried in that file and removed. It fails under the test
settings with `admin.E406`, because `recipes/test_settings.py:25-33` deliberately
uninstalls `django.contrib.messages`, and warns about a missing vite manifest until
`yarn build` has run. Both are true statements about the *test environment*, not about the
project, so asserting on them would have made the baseline a test of the settings module.

**Alternative rejected — run the named AC against PostgreSQL so nothing skips.** It would
let AC1 keep naming the whole suite, and it would close a real gap (production is
PostgreSQL 16; those 18 search tests never run locally). Rejected *here* because it makes
the north star's own acceptance depend on a database service that is not present in a
clean checkout — an environment-bound green that silently becomes a skip the moment the
service is absent. The gap is real and is recorded in REQ-001's Notes with a named home,
not dropped.

**Alternative rejected — drop `REQ-001` from the downstream `depends_on` lists.** It would
unblock REQ-002 in one edit and cost no test run. Rejected because it defers the baseline
question to REQ-002's first land gate, where a pre-existing red would be indistinguishable
from damage REQ-002 caused, and because a north star that nothing depends on stops being
load-bearing.

**Alternative rejected — flip REQ-001 to `done` by hand.** Certifies a green nobody
observed; the exact hollow-REQ shape the acceptance taxonomy exists to prevent.

## Build sequence

1. Run `.venv/bin/python -m pytest --no-cov` and read the result honestly. A red here is a
   finding about the fork's inherited state, not a failure of this checkpoint — it gets
   surfaced, not worked around. *(Done: 1254 passed, 18 skipped.)*
2. Add `cookbook/tests/other/test_baseline.py::test_no_missing_migrations`.
3. Repoint REQ-001's AC1 at that test, and record in REQ-001's Notes both why the AC
   changed and the PostgreSQL skip gap it exposed.
4. Leave `status:` and the index row alone — `steward checkpoint` owns the flip.
5. Close with `steward checkpoint REQ-001 develop`.

Nothing else in the repo is touched. REQ-002's `draft → open` frontmatter and index flip
from `steward activate` is already in the working tree and will ride this checkpoint's
whole-tree commit, which is the intended behaviour (one session at a time) and leaves
`steward lint` in lockstep either way.

## Verification

AC1 re-run independently by `steward checkpoint` through the land-grade gate: the full
suite must pass, with no skipped-or-zero-collection escape (skip ≠ green). REQ-001 has no
`artifact` or `manual` criterion, so a green gate lands it outright and REQ-002's develop
step becomes eligible — which is the observable result this checkpoint is for.
