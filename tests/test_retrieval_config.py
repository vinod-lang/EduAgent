import pytest
from config import ConfigurationError, get_ai_config
from retrieval_config import get_retrieval_config, RetrievalConfig

@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    for key in ('EDUAGENT_RAG_DISTANCE_THRESHOLD', 'EDUAGENT_RAG_CANDIDATE_K', 'EDUAGENT_RAG_FINAL_K', 'EDUAGENT_RAG_MAX_DISTANCE'):
        monkeypatch.delenv(key, raising=False)


def test_rag_defaults():
    assert get_retrieval_config() == RetrievalConfig(15, 5, 0.50)


def test_rag_overrides(monkeypatch):
    monkeypatch.setenv('EDUAGENT_RAG_CANDIDATE_K', '20')
    monkeypatch.setenv('EDUAGENT_RAG_FINAL_K', '7')
    monkeypatch.setenv('EDUAGENT_RAG_MAX_DISTANCE', '0.4')
    assert get_retrieval_config() == RetrievalConfig(20, 7, 0.4)
    assert get_retrieval_config(candidate_k=10, final_k=2, max_distance=0.3) == RetrievalConfig(10, 2, 0.3)


@pytest.mark.parametrize('key,value', [('EDUAGENT_RAG_CANDIDATE_K', 'bad'), ('EDUAGENT_RAG_CANDIDATE_K', '0'), ('EDUAGENT_RAG_CANDIDATE_K', '-1'), ('EDUAGENT_RAG_CANDIDATE_K', '3'), ('EDUAGENT_RAG_CANDIDATE_K', '201'), ('EDUAGENT_RAG_FINAL_K', '0'), ('EDUAGENT_RAG_FINAL_K', '16'), ('EDUAGENT_RAG_FINAL_K', '1.5'), ('EDUAGENT_RAG_MAX_DISTANCE', 'nan'), ('EDUAGENT_RAG_MAX_DISTANCE', 'inf'), ('EDUAGENT_RAG_MAX_DISTANCE', '-0.1'), ('EDUAGENT_RAG_MAX_DISTANCE', '2.1'), ('EDUAGENT_RAG_MAX_DISTANCE', ''), ('EDUAGENT_RAG_MAX_DISTANCE', 'bad')])
def test_invalid_rag_environment(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigurationError): get_retrieval_config()


@pytest.mark.parametrize('kwargs', [{'candidate_k':True}, {'final_k':1.1}, {'max_distance':True}, {'max_distance':'0.5'}, {'candidate_k':2, 'final_k':3}])
def test_invalid_explicit_configuration(kwargs):
    with pytest.raises(ConfigurationError): get_retrieval_config(**kwargs)


@pytest.mark.parametrize('threshold', [0, 0.65, 2])
def test_cosine_threshold_range(threshold):
    assert get_retrieval_config(max_distance=threshold).max_distance == threshold


def test_retrieval_config_is_independent(monkeypatch):
    before = get_ai_config()
    monkeypatch.setenv('EDUAGENT_RAG_MAX_DISTANCE', '0.2')
    assert get_ai_config() == before
    monkeypatch.setenv('EDUAGENT_LLM_PROVIDER', 'invalid')
    assert get_retrieval_config().max_distance == 0.2
