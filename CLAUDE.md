# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Tandoor Recipes — a self-hosted recipe manager. Django 5.2 + DRF backend (single app `cookbook`), Vue 3
SPA frontend (`vue3/`) that talks to the backend exclusively through a **generated** TypeScript API client.
Default branch is `develop`.

This repo is a **fork** of upstream `TandoorRecipes/recipes`, run for the owner's own household;
upstreaming individual changes is opportunistic, not the goal. The frozen statement of purpose is
[`requirements/REQ-001.md`](requirements/REQ-001.md).

## Working under DevSteward

This project is managed by the **DevSteward** engine (the `steward` CLI). Read
[`STEWARD.md`](STEWARD.md) — it is the manual and the public interface. Treat the engine as a
black box: use the CLI and the docs, never read or patch engine source from here.

- **Requirements are the unit of work.** Every change starts as a REQ in **`requirements/`**
  with a row in [`REQUIREMENTS_INDEX.md`](requirements/REQUIREMENTS_INDEX.md). New idea →
  `/intake`; work the next step → `/advance`. Don't hand-write REQ files from scratch.
- **Path deviation:** `STEWARD.md` documents the conventional layout under `docs/`; this repo
  keeps every engine document top-level so the mkdocs `gh-deploy` workflow does not publish it —
  `requirements/`, `requirements/plans/`, `requirements/concepts/`, set via `requirements_dir`,
  `index_file`, `plans_dir` and `concepts_dir` in `.devsteward/config.yaml` (all four became
  configurable in DevSteward REQ-084; the earlier `exclude_docs` workaround in `mkdocs.yml` is
  gone with it).
- **Status has exactly one source: the index row ↔ REQ frontmatter pair**, kept in lockstep by
  `steward lint` and read live by `steward status`. Never record status anywhere else.
- **Same-commit discipline:** a REQ's frontmatter, its row in the index, and the code that
  satisfies it move in the **same** commit.
- **The ledger contract.** Checkpoint state lives in `.devsteward/state.yaml` (cursor) and
  `.devsteward/events.jsonl` (append-only log) — **never** in the REQ files. `.devsteward/` is
  committed; it is part of this project's history. Running acceptance tests and recording parked
  decisions are the *engine's* job, not a session's.
- **Branching model — trunk-based.** All work lands on **`develop`**: REQ intake, plans, the
  ledger, and implementation (code + tests + the status flip to `done`) all commit directly to
  `develop`. `master` is production/released. No feature branches, no worktrees, no
  engine-initiated branch switching. Note these are *upstream's* names — DevSteward's own
  defaults are `main`/`dev`, remapped in `.devsteward/config.yaml`. Never commit to `master`.
- **Land gate.** `steward` verifies a REQ by running its named acceptance tests plus the full
  suite (`python -m pytest --no-cov`, run under `.venv/bin/python` — both configured under
  `verify:` in `.devsteward/config.yaml`, which is also where the venv is named since it is not
  active in agent or headless shells).
  A skipped or zero-collection named test **fails** the gate — skip ≠ green.
- **Upstream rebases.** Because every local divergence is a REQ, a rebase onto upstream
  `develop` should be reviewable REQ by REQ. Prefer plugins (`recipes/plugins/<name>/`) and
  settings over forked core code — see REQ-001 Decision 5.
- **Co-author trailer** on commits:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## Commands

### Backend

```bash
pip install -r requirements.txt
python manage.py migrate            # SQLite by default, no env vars needed
DEBUG=1 python manage.py runserver
python manage.py collectstatic      # needed after `yarn build` if not running the vite dev server
```

### Frontend

```bash
cd vue3 && yarn install
yarn dev      # vite dev server on :5173 — start this BEFORE runserver (see django-vite note below)
yarn build    # builds into cookbook/static/vue3/
```

### Tests

`pytest.ini` sets `DJANGO_SETTINGS_MODULE=recipes.test_settings` and hardcodes `-n auto` plus coverage
into `addopts`, so plain invocations always run the full parallel suite with coverage.

```bash
pytest                                                   # full suite
PYTEST_ADDOPTS="--no-cov -n 0" pytest cookbook/tests/api/test_api_food.py            # one file
PYTEST_ADDOPTS="--no-cov -n 0" pytest cookbook/tests/api/test_api_food.py::test_list_space
```

Coverage and xdist fight each other; always pass `--no-cov -n 0` when running a single test or debugging.
Tests default to SQLite; point at Postgres with the `TEST_*` env vars read by `recipes/test_settings.py`
(`TEST_DATABASE_URL`, `TEST_POSTGRES_HOST`, …). Search and Food behaviour differs between the two backends —
changes there should be verified against both.

### Lint / format (required for contributions)

Line length is **179** everywhere (flake8, yapf, isort, prettier).

```bash
flake8 file.py --ignore=E501 | isort -q file.py | yapf -i file.py
prettier --write file.vue
```

Prettier ignores `vue3/src/openapi/`, `*.html`, and `*.yml` — never reformat Django templates or workflows.

### Regenerating the API client

`vue3/src/openapi/` is generated and **must not be hand-edited**. With the Django dev server running on
:8000 and `openapi-generator-cli` (needs Java) on PATH:

```bash
python scripts/generate_api_client.py
```

It wipes `apis/`, `models/`, `index.ts` and regenerates from `http://127.0.0.1:8000/openapi/` using the
custom mustache templates in `vue3/src/openapi/templates`. Any API change (serializer field, viewset action,
drf-spectacular annotation) requires regenerating, or the frontend types silently drift.

### Translations

Backend strings live in `cookbook/locale/<lang>/LC_MESSAGES/django.po` (managed by Weblate); frontend
strings in `vue3/src/locales/<lang>.json`. Regenerate/compile the backend catalogs with:

```bash
python scripts/make_compile_messages.py
```

Do not hand-edit non-English translation files — they come from Weblate.

## Architecture

### Space scoping (the single most important invariant)

Tandoor is multi-tenant: every object belongs to a `Space`. Almost every model uses
`objects = ScopedManager(space='space')` from **django-scopes**, so any ORM query outside an active scope
raises. `cookbook/helper/scope_middleware.py::ScopeMiddleware` resolves the request's active `UserSpace`,
sets `request.space` / `request.user_space`, and wraps the view in `with scope(space=request.space)`.
It also carves out explicit exceptions (`/api/user-preference/`, `/admin/`, `/accounts/`, share-link recipe
GETs, unauthenticated requests) that run under `scopes_disabled()`.

Consequences:
- Code running outside a request (management commands, signals, background threads, fixtures) must open its
  own `scope(space=...)` or `scopes_disabled()`.
- `cookbook/tests/conftest.py` installs a `pytest_fixture_setup` hookwrapper that wraps all non-generator
  fixtures in `scopes_disabled()`; tests that touch the ORM directly usually need `with scopes_disabled():`
  or `with scope(space=space_1):`.

### Permissions

Layered and largely hand-rolled in `cookbook/helper/permission_helper.py`:
1. Django groups `guest` / `user` / `admin` (never rename them — the system matches on name), checked via
   `has_group_permission`, `@group_required`, `GroupRequiredMixin`.
2. Space membership through `UserSpace`, plus `Household` grouping for shopping/meal-plan sharing
   (`is_object_household`, cached — see `invalidate_household_cache`).
3. Object level: owner / shared / share-link (`CustomIsOwner`, `CustomIsShared`, `CustomIsShare`,
   `CustomRecipePermission`, …) used as DRF `permission_classes`.
4. OAuth token scopes via `CustomTokenHasScope` — these check *only* scopes and must always be combined
   with one of the classes above.
5. Space limits (`above_space_limit`, `above_space_recipe_limit`, `above_space_user_limit`) for hosted setups.

`django superuser` bypasses everything.

### Models (`cookbook/models.py`, ~1700 lines)

- `PermissionModelMixin` gives every model `get_space()` / `get_owner()` / `get_shared()`; `get_space_key()`
  is overridden when space is reached indirectly (e.g. `space='recipe__space'`).
- `Food` and `Keyword` are django-treebeard `MP_Node` trees via `TreeModel` + `TreeManager`; they support
  move and merge operations and inheritance (`FoodInheritField`) — tree-aware querysets need
  `get_descendants_and_self` style helpers rather than plain filters.
- `MergeModelMixin` powers the merge/rename features for foods, units, keywords, categories.

### API layer

`cookbook/views/api.py` (~3400 lines) holds all viewsets; `cookbook/urls.py` registers them on a DRF
router extended to absorb plugin routers. Reusable behaviour is composed from mixins defined at the top of
that file: `LoggingMixin`, `StandardFilterModelViewSet` (query/updated_at/limit/random params),
`FuzzyFilterMixin`, `ExtendedRecipeMixin` (annotates `recipe_image`/`recipe_count`), `MergeMixin`,
`TreeMixin`, `DeleteRelationMixing`, and `DefaultPagination` (page size 50/max 200, adds a server
`timestamp` to every paginated response — the frontend relies on it for sync).

Serializers live in `cookbook/serializer.py`: `SpacedModelSerializer` injects `request.space` on create,
`SpaceFilterSerializer` filters nested lists to the active space, and `WritableNestedModelSerializer`
(drf-writable-nested) handles nested recipe/step/ingredient writes. The schema is served by drf-spectacular
at `/openapi/` with docs at `/docs/api/` and `/docs/swagger/`.

### Frontend

`vue3/` — Vite + Vuetify 3 + Pinia + vue-i18n, single entry `src/apps/tandoor/main.ts` which also defines
the vue-router route table.

Django serves the SPA from a catch-all route (`cookbook/urls.py` → `views.index` →
`cookbook/templates/frontend/tandoor.html`) using **django-vite**. `recipes/settings.py` probes
localhost:5173 at startup: if the vite dev server answers *and* `DEBUG` is on, HMR mode is enabled;
otherwise it falls back to the built manifest. This is why the vite dev server must be started before
`runserver`.

**Generic model system** — `vue3/src/types/Models.ts` defines a `Model` descriptor and a `SUPPORTED_MODELS`
registry (`registerModel`, `getGenericModelFromString`, `GenericModel`). `ModelListPage.vue`,
`ModelEditPage.vue`, `ModelDeletePage.vue` and `DatabasePage.vue` are driven entirely off those descriptors
(table headers, which CRUD verbs exist, merge/tree support, editor component). Adding CRUD UI for a new
model usually means adding a descriptor there plus an editor component — not writing new pages.

State lives in a handful of Pinia stores (`src/stores/`). `ShoppingStore.ts` in particular maintains a
retry queue for requests that fail while offline and reconciles local edits against the server `timestamp`
returned by `DefaultPagination` — be careful when touching its update paths.

### Search

`cookbook/helper/recipe_search.py` — the `RecipeSearch` class builds a queryset from user
`SearchPreference` / `SearchFields` plus request params. `_is_postgres()` gates full-text and
TrigramSimilarity features; SQLite falls back to simpler `icontains` behaviour. Sort order and filter
parsing are separated into module-level helpers.

### Import / export, connectors, AI

- `cookbook/integration/` — one class per external recipe manager (Mealie, Paprika, Chowdown, …), all
  subclassing `integration.Integration`, dispatched by `get_integration()` in `cookbook/views/import_export.py`.
  Adding a format means adding a class plus wiring it into that dispatcher and the form choices.
- `cookbook/connectors/` — outbound integrations (e.g. Home Assistant) driven by a background
  `ConnectorManager` worker thread. Disabled in tests via `DISABLE_EXTERNAL_CONNECTORS` because the thread
  holds a DB connection.
- `cookbook/helper/ai_helper.py` — AI features (image recognition, step sorting, nutrition) go through
  **litellm** with per-space `AiProvider` config and `AiLog` accounting; endpoints are rate-throttled.

### Plugins

Optional plugins are dropped into `recipes/plugins/<name>/`. `recipes/settings.py` discovers them into
`PLUGINS`, `recipes/urls.py` mounts their urls, `cookbook/urls.py` extends the DRF router with their
routers, and `vue3/vite.config.ts::collectBuildInputs()` scans `vue3/src/plugins/*/plugin.ts` for extra
build inputs. `plugin.py` and `version.py` at the repo root handle plugin linking and version reporting.

## Conventions and gotchas

- New API-visible behaviour needs a pytest test — see `cookbook/tests/api/` for the per-endpoint pattern
  (`register(Factory, 'obj_1', space=LazyFixture('space_1'))`, `LIST_URL`/`DETAIL_URL` constants, and the
  `a_u`/`g1_s1`/`u1_s1`/`a1_s1`/`s1_s1` client fixtures covering anonymous/guest/user/admin/superuser in
  two spaces).
- There is no frontend test suite; vue3 changes are verified manually.
- Larger features should be discussed before implementation (see `docs/contribute/guidelines.md`);
  contributions require signing the CLA.
- Docs are mkdocs-material under `docs/` with nav in `mkdocs.yml`.
