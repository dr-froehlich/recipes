"""Acceptance tests for REQ-009 AC1 and AC2 — the fork's CI is wired to actually run.

Both are `regression`: they parse the committed workflows and need nothing but a checkout,
so they cannot skip. AC3 — that the workflow *did* run and pass on GitHub — is graded from
captured evidence in ``test_ci_run_signoff.py``.

The defect these guard against is a workflow that reports success without executing: on a
fork, ``if: github.repository_owner == 'TandoorRecipes'`` makes a job skip, and a skipped
run is not a failed run. So the assertions here are deliberately about *reachability* —
whether a check can run at all — not about the presence of the right YAML keys.
"""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / '.github/workflows'
DOCS_DIR = REPO_ROOT / 'docs'

# The three workflows this fork depends on and that must never be owner-gated (Decision 1).
UNGATED_WORKFLOWS = ('ci.yml', 'codeql-analysis.yml', 'docs.yml')

UPSTREAM_OWNER = 'TandoorRecipes'
UPSTREAM_DOCS_DOMAIN = 'docs.tandoor.dev'

# The engine recipes/test_settings.py must end up selecting, and the variables it reads.
POSTGRES_ENGINE = 'django.db.backends.postgresql'
LOCAL_HOSTS = ('localhost', '127.0.0.1')


def _load(name):
    path = WORKFLOWS / name
    assert path.is_file(), f'{path} is missing'
    return yaml.safe_load(path.read_text(encoding='utf-8'))


def _conditions(node):
    """Every `if:` expression anywhere in a job — job level and step level alike."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'if':
                found.append(str(value))
            else:
                found += _conditions(value)
    elif isinstance(node, list):
        for item in node:
            found += _conditions(item)
    return found


# ------------------------------------------------------------------------------------
# AC1 — no check the fork depends on is silently gated off
# ------------------------------------------------------------------------------------
def test_no_owner_gates():
    """The fork's checks can run, and the fork's *build* is not broken making that true.

    Two halves, and the second is the load-bearing one. Removing every owner condition in
    the tree would satisfy the first half while breaking `build-docker.yml` — that workflow's
    gates guard upstream-only credentials and publish targets (REQ-002, REQ-009 Decision 2),
    and are not the same defect. So the four survivors are each located specifically.
    """
    # 1. None of the three workflows conditions anything on the repository owner.
    for name in UNGATED_WORKFLOWS:
        workflow = _load(name)
        for job_name, job in workflow['jobs'].items():
            for condition in _conditions(job):
                assert 'repository_owner' not in condition, (
                    f'{name}: job {job_name!r} is still gated on the repository owner '
                    f'(if: {condition!r}) — on this fork it would skip and report success'
                )

    # 2. The four owner conditions in build-docker.yml that guard upstream-only things are
    #    still there. Each is checked where it lives, so this cannot pass on a count.
    docker = _load('build-docker.yml')
    build_job = docker['jobs']['build-container']

    login_steps = [s for s in build_job['steps'] if 'login' in str(s.get('name', '')).lower() and UPSTREAM_OWNER in str(s.get('if', ''))]
    assert login_steps, ('the Docker Hub login step no longer carries its owner gate — a fork would try to log in '
                         "with credentials it does not have")

    meta_steps = [s for s in build_job['steps'] if str(s.get('uses', '')).startswith('docker/metadata-action')]
    assert meta_steps, 'no docker/metadata-action step found in build-container'
    images = str(meta_steps[0]['with']['images'])
    assert UPSTREAM_OWNER in images, ("the image list no longer gates upstream's Docker Hub image name on the owner — "
                                      f'a fork would try to publish to it:\n{images}')

    for job_name, ref_guard in (('notify-stable', 'refs/tags/'), ('notify-beta', 'refs/heads/beta')):
        job = docker['jobs'].get(job_name)
        assert job is not None, f'the {job_name} job is gone from build-docker.yml; expected jobs: {sorted(docker["jobs"])}'
        condition = str(job.get('if', ''))
        assert ref_guard in condition, f'{job_name} no longer guards on {ref_guard!r} (if: {condition!r})'
        assert UPSTREAM_OWNER in condition, (f'{job_name} lost its owner gate (if: {condition!r}); it announces releases to '
                                             "upstream's Discord and must stay upstream-only")

    # 3. Nothing *claims* upstream's verified custom domain (Decision 7). Prose links to
    #    docs.tandoor.dev are ordinary inherited content and are left alone — what would
    #    hijack the domain is a CNAME file, which is the only thing gh-deploy publishes as
    #    a domain claim, or a site_url pointing there.
    claimants = [p for p in DOCS_DIR.rglob('CNAME') if p.is_file() and UPSTREAM_DOCS_DOMAIN in p.read_text(encoding='utf-8')]
    assert not claimants, (
        f"{[str(p.relative_to(REPO_ROOT)) for p in claimants]} still claims upstream's domain "
        f'{UPSTREAM_DOCS_DOMAIN!r}; with docs.yml ungated, this fork would deploy a Pages site '
        'claiming a domain it does not own'
    )

    site_url = (yaml.safe_load(re.sub(r'!!python/name:\S+', "''", (REPO_ROOT / 'mkdocs.yml').read_text(encoding='utf-8'))) or {}).get('site_url', '')
    assert UPSTREAM_DOCS_DOMAIN not in str(site_url), f'mkdocs.yml still points site_url at {site_url!r}'


# ------------------------------------------------------------------------------------
# AC2 — the CI workflow declares the checks this REQ adds
# ------------------------------------------------------------------------------------
def _ci_job():
    workflow = _load('ci.yml')
    jobs = workflow['jobs']
    assert len(jobs) == 1, f'expected ci.yml to define exactly one job, found {sorted(jobs)}'
    return next(iter(jobs.values()))


def _step_env(step):
    return {str(k): str(v) for k, v in (step.get('env') or {}).items()}


def test_ci_declares_postgres_and_vitest():
    """PostgreSQL reaches pytest, and the frontend suite runs unconditionally.

    Every clause is asserted on its own, so removing any single one of them fails here.
    """
    job = _ci_job()
    steps = job['steps']

    # --- the service container -------------------------------------------------------
    services = job.get('services') or {}
    assert services, 'ci.yml declares no service container — pytest would fall back to SQLite'

    pg_name, pg_service = None, None
    for name, service in services.items():
        if re.match(r'^(docker\.io/)?(library/)?postgres:', str(service.get('image', ''))):
            pg_name, pg_service = name, service
            break
    assert pg_service is not None, (f'no postgres service among {sorted(services)}; production runs PostgreSQL 16 and the '
                                    'tests marked requires_postgres would skip')

    image = str(pg_service['image'])
    version = image.split(':', 1)[1].split('-')[0]
    assert version.split('.')[0] == '16', f'the service runs {image!r}, not a postgres 16 image'

    assert 'health' in str(pg_service.get('options', '')
                           ), (f'the {pg_name!r} service declares no health check — pytest can start before the '
                               'database accepts connections and fail intermittently')

    service_env = {str(k): str(v) for k, v in (pg_service.get('env') or {}).items()}

    # --- the pytest step, and how it reaches that service ----------------------------
    pytest_steps = [s for s in steps if re.search(r'(^|\s)pytest(\s|$)', str(s.get('run', '')))]
    assert len(pytest_steps) == 1, f'expected exactly one step invoking pytest, found {len(pytest_steps)}'
    pytest_step = pytest_steps[0]
    env = _step_env(pytest_step)

    # recipes/test_settings.py only builds a PostgreSQL config when the engine says so;
    # pointing TEST_POSTGRES_* at a server while the engine stays sqlite3 silently does nothing.
    engine = env.get('TEST_DB_ENGINE', '')
    url = env.get('TEST_DATABASE_URL', '')
    assert engine == POSTGRES_ENGINE or url.startswith('postgres'), (
        f'the pytest step selects no PostgreSQL engine (TEST_DB_ENGINE={engine!r}, '
        f'TEST_DATABASE_URL={url!r}) — the suite would still run on SQLite'
    )

    for key in ('TEST_POSTGRES_USER', 'TEST_POSTGRES_PASSWORD', 'TEST_POSTGRES_DB'):
        assert env.get(key), f'{key} is not passed to the pytest step'

    # The credentials must be the ones the service was started with, or the connection fails.
    assert env['TEST_POSTGRES_USER'] == service_env.get('POSTGRES_USER'), 'the pytest step and the postgres service disagree about the user'
    assert env['TEST_POSTGRES_PASSWORD'] == service_env.get('POSTGRES_PASSWORD'), 'the pytest step and the postgres service disagree about the password'

    # The host must actually reach the declared service. Service-name DNS resolves only when
    # the job itself runs in a container; otherwise the service is reachable through a
    # published port on localhost. Check the property, not a literal hostname.
    host = env.get('TEST_POSTGRES_HOST', '')
    assert host, 'TEST_POSTGRES_HOST is not passed to the pytest step'
    if job.get('container'):
        assert host == pg_name, (f'the job runs in a container, where the service is reached by its name {pg_name!r}, but the host is {host!r}')
    else:
        assert host in LOCAL_HOSTS, (f'the job runs directly on the runner, where {pg_name!r} does not resolve; '
                                     f'the host must be a local address, not {host!r}')
        published = [str(p) for p in (pg_service.get('ports') or [])]
        assert published, (f'the {pg_name!r} service publishes no port, so nothing on {host} reaches it')

    # --- the junit the live sign-off is graded from ----------------------------------
    assert '--junitxml' in str(pytest_step['run']), 'the pytest step writes no junit XML; AC3 has nothing to grade the live run from'
    upload_steps = [s for s in steps if str(s.get('uses', '')).startswith('actions/upload-artifact')]
    assert upload_steps, 'the junit XML is never uploaded, so it exists only inside the runner and cannot be captured'

    # --- the frontend suite ----------------------------------------------------------
    vitest_steps = [s for s in steps if re.search(r'\byarn\b.*\btest\b', str(s.get('run', ''))) or 'vitest' in str(s.get('run', ''))]
    assert vitest_steps, 'no step invokes the vue3 vitest suite'
    for step in vitest_steps:
        assert not step.get('if'), (f'the vitest step is conditional (if: {step["if"]!r}); a frontend suite that can skip is the '
                                    'same silent no-op this REQ exists to remove')

    # It has to find node_modules. Everything it depends on must be unconditional too.
    install_steps = [s for s in steps if 'yarn install' in str(s.get('run', '')) or str(s.get('uses', '')).startswith('actions/setup-node')]
    assert install_steps, 'nothing sets up Node or installs the vue3 dependencies'
    for step in install_steps:
        assert not step.get('if'), (
            f'{step.get("name", step.get("uses"))!r} is conditional (if: {step["if"]!r}), so on a cache hit the '
            'vitest step would run without dependencies'
        )
