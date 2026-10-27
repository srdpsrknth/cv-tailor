import shutil
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tests'))

PROFILES = ROOT / 'tests' / 'fixtures' / 'profiles'

from support import (  # noqa: E402
    OfflineGemini,
    copy_content_json,
    job_description,
    load_profile,
    make_blank_pdf,
    recorded_session,
)


@pytest.fixture(scope='session')
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope='session')
def synthetic_store(tmp_path_factory) -> Path:
    """A profile store holding both synthetic fixtures, outside the repository.

    The suite must never read the owner's real profiles (ADR 0011), and the tests
    need a store that is *populated* for the multi-profile paths to be exercised at
    all. Both fixture profiles are copied in under their own ids.
    """
    root = tmp_path_factory.mktemp('profile-store')
    profiles = root / 'profiles'
    for profile_id, fixture in (('analyst_a', 'synthetic_analyst'),
                                ('marketer_b', 'synthetic_marketer')):
        directory = profiles / profile_id
        directory.mkdir(parents=True)
        shutil.copy2(PROFILES / f'{fixture}.yaml', directory / 'profile.yaml')
    return root


@pytest.fixture(autouse=True)
def _select_a_profile(monkeypatch, synthetic_store):
    """Give every test an explicit profile id and a synthetic store.

    ``profile_id`` fails closed (ADR 0003), so ``tailor_documents`` raised for the
    whole suite as soon as the store landed: the pre-existing tests call it with no
    config and no id, which is now a genuine error rather than a default.

    Rather than edit 32 test bodies to thread an argument they are not about, both
    values are supplied here, once, in the environment the code reads at call time.

    Two things matter about doing it this way:

    * it does **not** weaken the rule -- the id is still explicit, just not written
      in each test. ``tests/test_profile_store.py`` asserts the fail-closed paths
      directly, with no fixture standing in the way;
    * the store is a throwaway directory, so no test can read or write the owner's
      real profiles.

    A test that wants a different candidate sets ``CVTAILOR_PROFILE_ID`` itself.
    """
    monkeypatch.setenv('CVTAILOR_PROFILE_ID', 'analyst_a')
    monkeypatch.setenv('CVTAILOR_STORE', str(synthetic_store))
    return 'analyst_a'



@pytest.fixture
def analyst_profile():
    """Profile A — has an employer with no bullets, projects, certifications and a visa."""
    return load_profile('synthetic_analyst')


@pytest.fixture
def profile_store(synthetic_store):
    """The throwaway store the suite is pointed at, holding both synthetic profiles."""
    from services.profile_store import ProfileStore

    return ProfileStore.at(synthetic_store)


@pytest.fixture
def marketer_profile():
    """Profile B — different shape: no projects, no visa, no certifications."""
    return load_profile('synthetic_marketer')


@pytest.fixture
def analyst_session():
    return recorded_session('analyst_nordwind')


@pytest.fixture
def marketer_session():
    return recorded_session('marketer_lumen')


@pytest.fixture
def nordwind_job_description() -> str:
    return job_description('nordwind_analytics_engineer')


@pytest.fixture
def lumen_job_description() -> str:
    return job_description('lumen_growth_analyst')


@pytest.fixture
def harbor_job_description() -> str:
    return job_description('harbor_marketing_data_analyst')


@pytest.fixture
def offline_service(monkeypatch):
    """Install an :class:`OfflineGemini` as the service the pipeline constructs.

    Returns a factory so a test can choose which recorded transcript to replay and how
    many pages each rendered CV should pretend to have.
    """
    from services import tailor_service as service

    created: list[OfflineGemini] = []

    def install(texts, inputs_per_call=100, outputs_per_call=20) -> OfflineGemini:
        offline = OfflineGemini(texts, inputs_per_call, outputs_per_call)
        created.append(offline)
        # `tailor_documents` calls LLMService() with no arguments.
        monkeypatch.setattr(service, 'LLMService', lambda *a, **kw: offline)
        return offline

    install.created = created
    return install


@pytest.fixture
def stub_renderers(monkeypatch, tmp_path):
    """Replace both renderers with page-count stubs, as the original suite does.

    Used by tests that assert orchestration behaviour rather than document output.
    Real rendering is covered by tests/test_renderers_documents.py.
    """
    from services import tailor_service as service

    pages = []
    cv_calls = []

    def install(page_sequence):
        pages.extend(page_sequence)
        remaining = iter(pages)

        def latex_factory(outputs_dir):
            renderer = Mock()

            def render(cv, profile, job_position=None):
                cv_calls.append(cv)
                count = next(remaining)
                return make_blank_pdf(Path(outputs_dir) / 'CV.pdf', count)

            renderer.render_cv.side_effect = render
            return renderer

        def docx_factory(outputs_dir):
            def render(*args, **kwargs):
                folder = Path(outputs_dir)
                docx = folder / 'cover_letter.docx'
                docx.parent.mkdir(parents=True, exist_ok=True)
                docx.write_bytes(b'docx')
                return str(docx), make_blank_pdf(folder / 'cover_letter.pdf', 1)

            renderer = Mock()
            renderer.render_cover_letter.side_effect = render
            return renderer

        monkeypatch.setattr(service, 'create_latex_renderer', latex_factory)
        monkeypatch.setattr(service, 'create_docx_renderer', docx_factory)

    install.cv_calls = cv_calls
    return install


@pytest.fixture
def isolated_service(monkeypatch, tmp_path):
    """Point `tailor_documents` at a temp project root and clear OUTPUTS_DIR mirroring.

    Since the store is authoritative for generated documents (ADR 0011), a temp
    project root needs its own store: this copies the synthetic profiles into
    ``<project_root>/profiles`` and points ``CVTAILOR_STORE`` at the project root
    itself. Outputs then land at ``<project_root>/outputs/<profile_id>/<job_id>/``,
    which is what the pipeline tests assert, and nothing touches the owner's real store.
    """
    from services import tailor_service as service

    project_root = tmp_path / 'project'
    project_root.mkdir(parents=True, exist_ok=True)
    # Root the store at the project root so ``<store>/outputs/<id>/<job>`` is exactly
    # ``<project_root>/outputs/<id>/<job>`` -- the path every pipeline test asserts.
    store_root = project_root
    for profile_id, fixture in (('analyst_a', 'synthetic_analyst'),
                                ('marketer_b', 'synthetic_marketer')):
        directory = store_root / 'profiles' / profile_id
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROFILES / f'{fixture}.yaml', directory / 'profile.yaml')

    monkeypatch.setattr(service, 'PROJECT_ROOT', project_root)
    monkeypatch.setenv('CVTAILOR_STORE', str(store_root))
    monkeypatch.delenv('OUTPUTS_DIR', raising=False)
    return project_root


@pytest.fixture
def source_folder(tmp_path):
    """Build the ``<application>/source/`` layout used by render_application.py."""
    def build(content_name: str = 'valid_content.json') -> Path:
        application = tmp_path / 'application'
        copy_content_json(application, content_name)
        return application

    return build


def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'requires_latex: slow test that compiles a document with pdflatex; '
        'deselect with -m "not requires_latex"',
    )
