import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
