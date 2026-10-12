import importlib.util
import sys
import types
import os
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import Mock
import pytest

# Establish guards before test modules are imported, not just in fixtures.
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
_TEST_STORAGE = tempfile.TemporaryDirectory(prefix='eduagent-suite-storage-')
_PREVIOUS_CHROMA_PATH = os.environ.get('EDUAGENT_CHROMA_PATH')
os.environ['EDUAGENT_CHROMA_PATH'] = str(Path(_TEST_STORAGE.name)/'chroma_db')
ROOT = Path(__file__).resolve().parents[1]


def runtime_inventory():
    paths = [ROOT/'eduagent.db']
    paths.extend(p for folder in ('uploads','chroma_db') for p in (ROOT/folder).rglob('*') if p.is_file())
    return {str(p.relative_to(ROOT)): (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in paths if p.is_file()}


_RUNTIME_BEFORE = runtime_inventory()


def pytest_sessionfinish(session, exitstatus):
    try:
        if runtime_inventory() != _RUNTIME_BEFORE:
            reporter = session.config.pluginmanager.get_plugin('terminalreporter')
            if reporter:
                reporter.write_line('ERROR: production runtime inventory changed during collection/tests.', red=True)
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
    finally:
        db.DB_PATH = _PREVIOUS_DB_PATH
        _TEST_STORAGE.cleanup()
        if _PREVIOUS_CHROMA_PATH is None:
            os.environ.pop('EDUAGENT_CHROMA_PATH', None)
        else:
            os.environ['EDUAGENT_CHROMA_PATH'] = _PREVIOUS_CHROMA_PATH
sys.path.insert(0, str(ROOT))
import db
_PREVIOUS_DB_PATH = db.DB_PATH
db.DB_PATH = str(Path(_TEST_STORAGE.name)/'eduagent.db')

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

@pytest.fixture
def agents(monkeypatch):
    vectors = types.ModuleType("vector_store")
    vectors.search_database = Mock(return_value={"documents": [["Synthetic PCA context"]], "metadatas": [[{"source":"PCA","unit":"Unit 1"}]]})
    vectors.get_all_chunks = Mock(return_value=(["Synthetic PCA context"], [{"source":"PCA","unit":"Unit 1"}]))
    vectors.add_pdf_to_database = Mock()
    class Collection:
        configuration = {'hnsw': {'space': 'cosine'}}
        def count(self): return 100
        def query(self, query_texts, n_results, where=None, include=None):
            clauses = where.get('$and', [where]) if where else []
            course = next((clause['course'] for clause in clauses if 'course' in clause), None)
            raw = dict(vectors.search_database(query_texts[0], n_results=n_results, course=course))
            documents = raw.get('documents', [[]])[0]
            raw.setdefault('ids', [[f'synthetic_chunk_{i}' for i in range(len(documents))]])
            raw.setdefault('distances', [[0.2] * len(documents)])
            return raw
    vectors.collection = Collection()
    vectors.get_collection = lambda: vectors.collection
    monkeypatch.setitem(sys.modules, "vector_store", vectors)
    loaded = {}
    for name in ["student_support_agent", "assessment_agent", "document_agent", "coordinator"]:
        spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded[name] = module
    loaded["vectors"] = vectors
    return loaded

@pytest.fixture
def mcq():
    return {"question":"Synthetic question?", "options":{"A":"One","B":"Two","C":"Three","D":"Four"}, "correct_answer":"A", "explanation":"Synthetic evidence", "source_chunk":0, "bloom_level":"Understand"}
