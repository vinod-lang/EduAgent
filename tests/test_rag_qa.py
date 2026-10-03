from unittest.mock import Mock
import pytest
import ai_provider
from retrieval import retrieve_evidence, RetrievalError
from rag_fixtures import Collection, row, managed

@pytest.fixture
def qa(agents, monkeypatch):
    module = agents['student_support_agent']
    provider = Mock(return_value='Synthetic grounded answer')
    monkeypatch.setattr(module.ai_provider,'generate_chat',provider)
    return module, agents['vectors'], provider


@pytest.mark.parametrize('scope,metadata', [({'course':'C'}, {'source':'PCA','course':'C','unit':'Legacy Unit'}), ({'course':'C','semester':'S','subject':'ML','unit':'U'},managed()), ({'material_id':'material-A'},managed()), ({'course':'C','unit':'U'},dict(managed(),source='lecture.png'))])
def test_qa_scopes_legacy_managed_ocr(qa,monkeypatch,scope,metadata):
    module,vectors,provider=qa
    monkeypatch.setattr(vectors,'collection',Collection([row(metadata=metadata)]))
    result=module.answer_question('PCA purpose?',filters=scope)
    assert result.retrieval_status=='evidence_found' and result.evidence_count==1
    assert result.answer=='Synthetic grounded answer'
    assert metadata['source'] in result.sources[0]
    assert result.retrieval.diagnostics.active_filters==scope
    assert 'PCA preserves variance.' in provider.call_args.kwargs['messages'][1]['content']
    answer,sources=result;assert answer==result[0] and sources==result[1]


@pytest.mark.parametrize('rows,scope', [([],{}), ([row(distance=.95)],{}), ([row(metadata=managed())],{'course':'Other'}), ([row(metadata={'course':'C','source':'PCA'})],{'course':'C','semester':'S'})])
def test_no_evidence_zero_generation(qa,monkeypatch,rows,scope):
    module,vectors,provider=qa
    monkeypatch.setattr(vectors,'collection',Collection(rows))
    result=module.answer_question('Unrelated question',filters=scope)
    assert result.retrieval_status=='no_evidence' and result.evidence_count==0 and result.sources==[]
    assert 'No sufficiently relevant' in result.answer
    provider.assert_not_called()


def test_source_deduplication_multiple_materials(qa,monkeypatch):
    module,vectors,provider=qa
    collection=Collection([row('a','Evidence A',metadata=managed()), row('b','Evidence B',metadata=managed()), row('c','Evidence C',metadata=dict(managed('material-B'),source='second.pdf'))])
    monkeypatch.setattr(vectors,'collection',collection)
    result=module.answer_question('Question')
    assert result.evidence_count==3 and len(result.sources)==2
    assert all('material-' not in label for label in result.sources)


@pytest.mark.parametrize('page', [None,2])
def test_model_cannot_create_page_provenance(qa,monkeypatch,page):
    module,vectors,provider=qa
    provider.return_value='My invented source is imaginary.pdf Page 999.'
    metadata=dict(managed(),page=page)
    monkeypatch.setattr(vectors,'collection',Collection([row(metadata=metadata)]))
    result=module.answer_question('Question')
    assert 'Page 999' in result.answer
    assert '999' not in str(result.sources) and 'imaginary.pdf' not in str(result.sources)
    assert result.retrieval.sources[0].page==page
    assert ('Page 2' in result.sources[0]) == (page==2)


def test_pdf_text_marker_does_not_invent_page(qa,monkeypatch):
    module,vectors,provider=qa
    monkeypatch.setattr(vectors,'collection',Collection([row(text='--- Page 15 --- OCR reference',metadata=managed())]))
    assert 'Page' not in module.answer_question('Question').sources[0]


def test_unicode_qa(qa,monkeypatch):
    module,vectors,provider=qa
    monkeypatch.setattr(vectors,'collection',Collection([row(text='講義 — résumé',metadata=dict(managed(),source='講義.png'))]))
    assert '講義.png' in module.answer_question('講義?').sources[0]


def test_provider_failure_propagates_after_evidence(qa,monkeypatch):
    module,vectors,provider=qa
    monkeypatch.setattr(vectors,'collection',Collection([row()]))
    provider.side_effect=ai_provider.AIConnectionError('Synthetic unavailable service')
    with pytest.raises(ai_provider.AIConnectionError):module.answer_question('Question')
    provider.assert_called_once()


def test_conflicting_scope_fails_before_generation(qa):
    module,vectors,provider=qa
    with pytest.raises(RetrievalError,match='Conflicting'):module.answer_question('Question',course='A',filters={'course':'B'})
    provider.assert_not_called()


def test_bad_metric_no_generation(qa,monkeypatch):
    module,vectors,provider=qa
    collection=Collection([row()]);collection.configuration={'hnsw':{'space':'l2'}}
    monkeypatch.setattr(vectors,'collection',collection)
    with pytest.raises(RetrievalError):module.answer_question('Question')
    provider.assert_not_called()


def test_identical_display_labels_do_not_spam_sources(qa,monkeypatch):
    module,vectors,provider=qa
    monkeypatch.setattr(vectors,'collection',Collection([row('a','Evidence A',metadata=managed('A')),row('b','Evidence B',metadata=managed('B'))]))
    result=module.answer_question('Question')
    assert result.evidence_count==2 and len(result.sources)==1
    assert {source.material_id for source in result.retrieval.sources}=={'A','B'}
