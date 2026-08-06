# Plan 0002 — REQ-002's develop checkpoint: fork image delivery

> Authored 2026-08-06. A plan is a thinking document: how a chunk of work will be
> approached, the alternatives weighed, the sequence. It is not a contract (REQs are).

## Context

Advances [REQ-002](../REQ-002.md) — "the fork can be built and run on the household host,
repeatably and without risking the database". REQ-002 is `develop: split` (Decision 8):
its build phase mutates a production host and its only database, so the deploy design is
reviewed with the owner before anything touches the host. **That review happened at the
top of this session**; its four outcomes are recorded under *Reviewed decisions* below and
are what the rest of this plan builds.

Two things are true of this checkpoint that are not true of most:

- **It is not finished when the tests are green.** AC3 (`artifact`) and AC4 (`manual`)
  mean the green develop gate only *commits* on `develop`; the flip to `done` waits for
  `steward validate REQ-002`. But Decision 7 says the live deploy is performed and iterated
  **inside this attended session** — the System Tester cannot fix anything, so routing the
  registry/auth/arm64/migration round-trips there would bounce a red back a whole session
  later. So this session drives the real deploy to working, and the validate step signs off
  a deployment that already works.
- **The work is mostly outside Python.** One CI workflow, three shell files, a runbook, and
  a test module that reads them. The only Django-side change is none at all: `version.py`
  already bakes the commit hash and branch into the image, which is what the *Observable
  result* checks.

## Reviewed decisions (the attended design review, Decision 8)

| # | Fork | Chosen | Why |
|---|------|--------|-----|
| A | How the fork's image name enters `build-docker.yml` | `ghcr.io/${{ github.repository }}` (expression) | One line; resolves to upstream's own image on upstream and to the fork's on the fork. No fork name hardcoded in CI, so the diff is genuinely offerable upstream and carries no dead weight across a rebase. Rejected: a literal `ghcr.io/dr-froehlich/recipes` third entry — a stricter AC1 string match, but hardcodes this fork forever |
| B | Where the `pg_dump` lands and what "restorable" means | Stream to the workstation; verify serverlessly with `pg_restore --list` **and** `pg_restore -f /dev/null` | Nothing is written to a root filesystem at 88 %, and the second command decompresses and emits *every* data block as SQL, so truncation or corruption anywhere in the archive is caught — without a postgres server, which is what makes AC2 testable at all. Rejected: restoring into a scratch DB on the host (two extra DB copies on a full disk, a full restore's CPU/RAM on a 3 GB box serving DNS and a password manager) and into a throwaway local container (real-restore proof, but makes docker + a matching postgres image a hard dependency of every deploy *and* of AC2) |
| C | Where the runbook lives | `deploy/README.md` | Next to the script. No `mkdocs.yml` nav edit, so nothing extra conflicts on an upstream rebase, and a fork-specific runbook stays out of Tandoor's published documentation site where it would read as advice to strangers. Rejected: `docs/install/fork-deploy.md` |
| D | Remote naming | `origin` = the fork, `upstream` = TandoorRecipes with push disabled | The near-universal convention: a bare `git push` on `develop` goes to the fork, and `git fetch upstream` stays available for the deferred rebase REQ (Decision 6). Rejected: keeping `origin` on upstream and adding a `fork` remote — less disruptive today, but inverts the convention so a stray `git push origin develop` targets a repo this fork cannot write to |

## A finding that had to be cleared first

`.devsteward/config.yaml` names `.venv/bin/python` as the gate's interpreter. **That venv was
absent from this workstation at the start of the session** — REQ-001 landed green against it
on 2026-07-30, so it existed and has since been removed. Rebuilding it on the box's ambient
`python3` (3.14, Ubuntu 26.04 having dropped 3.13) fails: `psycopg2-binary==2.9.10` publishes
no cp314 wheel and its source build needs `libpq-dev`, which needs root.

Resolved by rebuilding on **Python 3.13 via `uv`** — the version the `Dockerfile` targets
(`FROM python:3.13-alpine3.23`), so the venv now matches production rather than merely
working. No pin in `requirements.txt` moved and no system package was installed. Recorded
here rather than silently fixed because the disappearance is a property of the workstation
that will recur, and because the alternative fixes (bumping `psycopg2-binary` to 2.9.12 for
a cp314 wheel; `sudo apt install libpq-dev`) would both have changed the project to suit a
broken environment.

## Approach

### Build — `.github/workflows/build-docker.yml`

Four edits, each reversible and each independently reviewable on a rebase:

1. **Drop the job gate** `if: github.repository_owner == 'TandoorRecipes'` from
   `build-container`. This is the whole reason the workflow silently produces nothing on a
   fork today.
2. **Gate the Docker Hub push to upstream.** Removing the job gate is *not* sufficient on
   its own, and this is the non-obvious part: `docker/login-action` for Docker Hub is gated
   only on `github.secret_source == 'Actions'`, which is **true** on the fork — secrets do
   come from Actions there, the repository just has none defined. So the fork would attempt
   a Docker Hub login with an empty username and fail the job before ever building. The
   login step and the `vabene1111/recipes` entry in the `images` list both become
   owner-conditional.
3. **Make the ghcr name follow the repository** — fork A above.
4. **Add `type=sha,format=long` to the tag list**, giving `sha-<40 hex>` alongside the
   existing `type=ref,event=branch` (`develop`). Decision 5: the sha is the only identifier
   that cannot drift, and it is what the deploy pins and what AC3 checks.

`platforms: linux/amd64,linux/arm64` and the `yarn install && yarn build` steps already sit
where they need to — the SPA is built into the gitignored `cookbook/static/vue3/` *before*
`docker/build-push-action` reads the build context. AC1 asserts that ordering precisely
because it is invisible and load-bearing: an image built without it starts cleanly and
serves no frontend at all.

### Deploy — `deploy/`

```
deploy/
  README.md           the runbook (fork C)
  deploy.sh           the procedure, run from the workstation over ssh
  verify_dump.sh      the backup gate, standalone so AC2 can exercise it directly
  target.env.example  every key documented, no real value
  .gitignore          target.env, dumps/
```

`verify_dump.sh` is split out of `deploy.sh` deliberately. AC2 has to prove the gate
*refuses* — a verifier reachable only by running the whole deploy could not be tested
without a household host, and would have to be asserted rather than observed.

`deploy.sh` in order, matching the REQ's five numbered steps, `set -euo pipefail`
throughout:

1. Source `deploy/target.env`; **exit non-zero if absent**, and exit non-zero if any
   required key is unset. Nothing is defaulted — a defaulted host is how a deploy hits the
   wrong machine.
2. `ssh $HOST 'docker compose … exec -T db pg_dump -Fc …' > dumps/<utc-ts>.dump`, then
   `verify_dump.sh` on it. Non-zero ⇒ stop, before anything else changes (Decision 4).
3. Write the resolved image reference (`ghcr.io/<owner>/recipes:sha-<40>`) into the stack's
   `.env` on the host and `docker compose up -d`.
4. `docker compose exec` the migrate command.
5. Print the version the host is now running, and the digest of the image it is running —
   the two things AC3 and AC4 read.

The sha defaults to `git rev-parse HEAD` and can be overridden by argument, so a rollback to
a previously published sha uses the same script rather than a remembered command line.

### Test module — `cookbook/tests/other/test_fork_delivery.py`

All four ACs name tests in this one module; AC3 and AC4 are `artifact`/`manual`, so their
tests are read by the System-Test phase against captured evidence, not by this session.

- **AC1** parses the workflow with PyYAML and asserts, structurally rather than by grep: no
  job-level `if` restricts `build-container` to the upstream owner; `linux/arm64` is in the
  platform list; the `images` list contains an entry that resolves to the fork's ghcr image
  when `github.repository` is `dr-froehlich/recipes` (so the expression form of fork A is
  checked by *evaluating* it, not by pattern-matching it); and the `yarn build` step's index
  precedes the `build-push-action` step's index.
- **AC2** drives `verify_dump.sh` as a subprocess against synthetic files: a truncated dump
  and a byte-corrupted dump must exit non-zero and say so, a well-formed dump must exit
  zero. The well-formed case needs a real custom-format archive; a fixture is generated once
  from an **empty scratch database** and committed under
  `cookbook/tests/other/test_data/`, so the test is deterministic, carries no household
  data, and needs no postgres server at test time — only the `pg_restore` binary the REQ's
  Notes already require.
- **AC3/AC4** read the evidence directory the System Tester captures (manifest inspection
  output, the host's running-image digest, the deploy console log, the sign-off record) and
  fail loudly when it is absent, so they can never pass by finding nothing.

## What this session does *not* do

Per Decision 6 and the REQ's Notes, and stated rather than silently omitted: no
upstream-rebase workflow, and no standing backup regime. The dump gate defends the deploy;
it does not become a schedule.

## Build sequence

1. Rebuild the gate's interpreter (above) and re-establish a green baseline before touching
   anything — a red inherited from the environment must not be mistaken for damage this REQ
   caused.
2. Wire the remotes (fork D).
3. Edit `build-docker.yml`; write `test_fork_delivery.py::test_build_workflow_is_fork_enabled`.
4. Write `deploy/verify_dump.sh` + the fixture; write
   `test_fork_delivery.py::test_dump_verification_rejects_unrestorable_dump`.
5. Write `deploy/deploy.sh`, `target.env.example`, `.gitignore`, `README.md`.
6. Write the AC3/AC4 evidence-reading tests.
7. Push `develop` to the fork; confirm the workflow runs, the arm64 image publishes, and the
   **package is public** — the REQ's named risk, because a private package would force a
   `docker login` on the host and contradict Decision 1.
8. Run the deploy against the household host and iterate until the site serves the fork
   image (Decision 7).
9. Leave `status:` and the index row alone — `steward checkpoint` owns the flip, and here it
   will *defer* the flip to the validate step because AC3/AC4 are artifact/manual.
10. Close with `steward checkpoint REQ-002 develop`.

## What actually happened

The build and deploy were carried out in this session (Decision 7). Recorded because
several things came out differently from the plan above:

**The fork's workflows were disabled, not broken.** After the workflow change landed, two
pushes produced *zero* runs — including `ci.yml` and `docs.yml`, which this REQ never
touched. GitHub disables all workflows on a newly created fork until the owner enables them
in the Actions tab; `GET /actions/permissions` reports `enabled: true` regardless, and
`PUT .../workflows/{id}/enable` returns success while changing nothing. Only the UI action
works. Worth knowing before diagnosing a workflow file that is in fact correct.

**`ci.yml` carries the same owner gate** (line 7) and skipped. So the fork's test suite does
not run in CI at all. Out of REQ-002's acceptance scope — its criteria are about the Docker
build — and therefore left for a follow-on REQ rather than widened into this one silently.

**The deploy is not the version jump it looked like.** The host ran release `2.6.13`; this
fork's `develop` descends from `2.6.11`. That reads like a downgrade, and is not: `2.6.13`
contains **zero** non-merge code commits that develop lacks (the 15 are release merges into
master plus a docs fix), and there is a **zero-migration delta** between them. The deploy
was therefore schema-neutral, and `migrate` reported `No migrations to apply.` on the live
database exactly as predicted.

**A rehearsal replaced the proposed data migration.** The operator's first instinct was to
stand a second instance up on a new hostname, hand-migrate the three recipes, retire the old
container and move DNS. Since the fork is the same application at an identical schema, there
was nothing to migrate between; that plan's only real risk was the hand-copying. Instead: a
throwaway stack on the host, its own database restored from a production dump, reached over
an SSH tunnel — no DNS, no proxy change, no Cloudflare app. It proved the arm64 image boots,
the SPA is present, the three recipes and their images render, and it **actually restored
the dump into a live cluster**, discharging by hand the one limitation `verify_dump.sh`
documents. Then it was torn down and the production stack was swapped in place.

**Two defects in the AC3 evidence contract, found by grading real evidence.** Both would
have failed the validate phase on a correct deploy:

1. `docker inspect` on a *container* has no `.RepoDigests` — that is an image field. The
   capture instruction had to resolve the container to its image first.
2. Pulling a multi-arch **tag** records the *index* digest, and `docker manifest inspect`
   prints only child manifests, never the index's own digest. Comparing the two sets could
   never match. Fixed by adding `index-digest.txt` from
   `docker buildx imagetools inspect --format '{{.Manifest.Digest}}'`.

This is the concrete argument for Decision 7: had the deploy been routed to the System-Test
phase, both defects would have surfaced there as a red, in a session that cannot fix
anything, and bounced back a whole session later.

## Verification

AC1 and AC2 are re-run independently by `steward checkpoint` through the land-grade gate,
alongside the full suite. Because REQ-002 declares `artifact` and `manual` criteria, a green
gate **commits on `develop` without landing**; `steward validate REQ-002` then runs the
System-Test phase for AC3 and AC4 and the flip follows from that.
