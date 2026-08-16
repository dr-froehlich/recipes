# Plan 0009 — REQ-009's develop checkpoint: fork CI, including PostgreSQL

> Authored 2026-08-16. A plan is a thinking document: how a chunk of work will be
> approached, the alternatives weighed, the sequence. It is not a contract (REQs are).

## Context

Advances [REQ-009](../REQ-009.md) — the fork's own checks start running in GitHub Actions,
against the database production actually uses.

The REQ froze the thinking: remove the owner gate from `ci.yml`, `codeql-analysis.yml` and
`docs.yml` (Decision 1) while leaving `build-docker.yml`'s four gates exactly as REQ-002 set
them (2); add a PostgreSQL 16 service container so the 18 `requires_postgres` tests execute
(3); run the `vue3` vitest suite unconditionally (4); no flake8 step (5); CI stays advisory
(6); `docs/CNAME` stops naming upstream's domain (7); and the proof that CI actually runs
green is this session's obligation, not the System Tester's (8).

Shape of the work: three one-line deletions, one service container, one env block, two
`if:` removals, two new steps, one deleted file, one new pytest module with two regression
tests, one new sign-off harness.

## The risk the REQ named, retired first

REQ-009's Notes call out one real unknown: the 18 tests marked `requires_postgres` have
**never executed anywhere**, so they might be substantially red, and the REQ pre-authorises
two outs (fix them here, or green-list the passing subset and home the rest in a follow-on
REQ). Everything else in this REQ is cheap; that one item could have been unbounded.

So it was settled before a single file was edited, using the shortcut the REQ's Notes
suggest — an ephemeral `postgres:16-alpine` container on the workstation, with the `TEST_*`
variables pointed at it:

```
cookbook/tests/other/test_recipe_search_text.py
cookbook/tests/other/test_recipe_search_integration.py   →  37 passed
full suite                                               →  1324 passed, 8 skipped
```

All 18 execute and all 18 pass, and nothing else in the suite regresses on PostgreSQL —
the 8 skips are the sign-off harnesses that skip by design outside a validation. **Neither
of the REQ's two outs is needed**; the PostgreSQL leg goes in whole, unconditioned. This
also means the local dry run and CI should agree, which makes a red CI run genuinely
informative rather than expected noise.

## Approach

### The forks this plan had to resolve

**Fork A — what does `docs/CNAME` become?** Decision 7 says it is "changed so it no longer
names upstream's domain; the fork publishes at its own `github.io` address", which reads as
a rewrite. Taken literally it has no correct content: a `CNAME` file exists solely to claim
a *custom* domain, and this fork has none. Writing `dr-froehlich.github.io` in there would
be worse than the status quo — that is the owner's **user**-site domain, and a project page
claiming it is a misconfiguration, not a fix. Publishing at `dr-froehlich.github.io/recipes/`
is precisely what GitHub Pages does when **no** `CNAME` file is present.

Resolved as **delete the file**. That is the state Decision 7 describes; "changed" was
wording written before the mechanism was checked. `mkdocs.yml` has no `site_url` and nothing
else in the tree references the domain, so the deletion is self-contained. AC1 is satisfied
as written — an absent file does not contain `docs.tandoor.dev` — and the acceptance test
asserts the stronger property directly: no file under `docs/` names upstream's domain.

**Fork B — does the service container reach pytest as a service *name* or as `localhost`?**
AC2 says the `TEST_*` variables must name "that service as the host". Service-name DNS
(`postgres:5432`) only resolves when the *job itself* runs inside a container; this job runs
directly on the runner, where the service is reachable only through a published port on
`localhost`. Containerising the whole job to make one hostname literal would be a large,
unrequested rewrite of upstream's job — against Decision 6's "the workflows are otherwise
not rewritten".

Resolved as **`localhost` plus an explicit `ports:` mapping**, with the acceptance test
checking the *property* rather than a literal string: it verifies the configured host
actually reaches the declared service — service name if the job is containerised, otherwise
`localhost`/`127.0.0.1` **and** a published port mapping on that service. That is a stronger
assertion than a string match, and it does not go red the day someone containerises the job.

**Fork C — the vitest step versus the static-files cache.** Upstream gates *four* steps on
`steps.django_cache.outputs.cache-hit != 'true'` — the Node setup, `yarn install`,
`yarn build` and `collectstatic`. Hanging a vitest step off that as-is gives a suite that
**passes by not running**: on any cache hit there is no `node_modules`, so `yarn test` either
errors or, worse, is itself made conditional and silently skips. That is the exact defect
this REQ exists to remove, reintroduced one layer down.

Resolved by making **Node setup and `yarn install` unconditional** and leaving `yarn build`
and `collectstatic` cache-gated. The frontend test suite needs dependencies, not a build, so
this costs a yarn install (cached by `actions/setup-node`) and buys a vitest step that cannot
skip. Two `if:` deletions.

### What the evidence gap forced

AC3 grades the live run from "the junit XML the workflow already produces
(`--junitxml=junit/test-results-*.xml`)". The workflow produces it — inside the runner, where
nothing can retrieve it. Producing and *retrievable* are not the same thing, and the System
Tester cannot capture a file that never leaves the runner.

So `ci.yml` also gains an `actions/upload-artifact` step, `if: always()` so a red run still
yields its junit. This is the one addition not spelled out in the REQ; it is what makes AC3's
named oracle exist at all.

### The acceptance tests

`cookbook/tests/other/test_ci_workflows.py` — AC1 and AC2, both `regression`, both pure YAML
parsing over the committed tree, so they need only a checkout and cannot skip.

- `test_no_owner_gates` walks every job in the three ungated workflows and fails on any
  `if:` mentioning `repository_owner`, then asserts the **four** `build-docker.yml` gates are
  still present by locating each one specifically (login step, image list, tag job, beta job).
  That second half is the load-bearing part: without it the criterion could be satisfied by
  deleting every owner condition in the tree, which would break the fork's own image build.
  It also asserts no file under `docs/` names `docs.tandoor.dev`.
- `test_ci_declares_postgres_and_vitest` asserts, individually so that removing any one of
  them fails: a service running a `postgres:16` image; a health check on it; the pytest step
  carrying `TEST_*` variables that select the PostgreSQL engine and point at that service
  (per fork B); the pytest step writing junit; an upload step for it; and an unconditional
  step invoking the vue3 vitest suite — *unconditional* checked explicitly, since a
  conditioned test step is the fork-C defect.

`cookbook/tests/other/test_ci_run_signoff.py` — AC3, `artifact`. Follows the harness pattern
already used by REQ-002/003/004/008: skips when `DEVSTEWARD_EVIDENCE_DIR` is unset, hard-fails
on missing evidence once it is set, so it cannot pass by finding nothing. It grades three
files captured from the real run — `run.json` (the workflow run's conclusion and status),
`test-results.xml` (the junit), and `steps.json` (the run's job/step list) — checking that the
run concluded `success` and was not skipped, that the junit records all 18 `requires_postgres`
tests as **executed rather than skipped**, and that the vitest step ran and did not skip.

The junit check is the one that matters: a green CI whose PostgreSQL tests skipped again is
exactly the failure this REQ exists to prevent, and it looks identical to success from the
run conclusion alone. The 18 are identified from the junit by classname/name against the list
the repo itself carries, so the count cannot drift silently.

### Decision 8's live proof

Push to `develop`, watch `Continuous Integration` on `dr-froehlich/recipes` with `gh run
watch`, and fix in place whatever the first real execution turns up. Mid-phase commits and
pushes are the sanctioned mechanism here (REQ-089's attended grant): a workflow's behaviour
is not knowable without pushing it. `steward checkpoint` is the terminal act, run once at the
end.

## Sequence

1. Local PostgreSQL dry run — **done**, see above.
2. Remove the three owner gates; delete `docs/CNAME`.
3. Rework `ci.yml`: service container, `TEST_*` env, unconditional Node/install, vitest step,
   junit upload.
4. Write both test modules; confirm AC1/AC2 green locally.
5. Commit, push, watch the run; iterate until `Continuous Integration` concludes success with
   the 18 executed and vitest run.
6. `steward checkpoint REQ-009 develop`.

## Out of scope

No flake8 step (Decision 5) — the lint gap stays a named follow-on REQ. `deploy/deploy.sh` is
untouched and a red CI does not block a deploy (Decision 6). Upstream's job structure, caching
strategy and action versions are otherwise left alone, so this stays a small reviewable diff
across rebases. Whether to actually enable GitHub Pages on the fork is left open; the site
stays dormant until a first `master` release regardless.
