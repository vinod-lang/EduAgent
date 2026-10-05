import pytest
from test_rag_qa import qa
from rag_fixtures import Collection,row

@pytest.mark.parametrize('distance,allowed',[(.49,True),(.50,True),(.5001,False),(.64,False),(.9,False)])
def test_profile_threshold_gate(qa,monkeypatch,distance,allowed):
    module,vectors,provider=qa
    monkeypatch.setattr(vectors,'collection',Collection([row(distance=distance)]))
    result=module.answer_question('Synthetic academic question')
    assert bool(result.evidence_count)==allowed
    if allowed:provider.assert_called_once()
    else:provider.assert_not_called();assert result.retrieval_status=='no_evidence'


def test_threshold_rollback_and_zero_provider_gate(qa,monkeypatch):
    module,vectors,provider=qa
    monkeypatch.setattr(vectors,'collection',Collection([row(distance=.60)]))
    assert module.answer_question('Synthetic').retrieval_status=='no_evidence'
    provider.assert_not_called()
    monkeypatch.setenv('EDUAGENT_RAG_DISTANCE_THRESHOLD','.65')
    assert module.answer_question('Synthetic').retrieval_status=='evidence_found'
    provider.assert_called_once()
