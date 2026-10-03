from unittest.mock import Mock
import pytest
from retrieval import build_filter, retrieve_evidence, normalize_results, RetrievalError
from rag_fixtures import Collection, row, managed


@pytest.mark.parametrize('filters,expected', [({}, None), ({'course':'C'}, {'course':'C'}), ({'course':'C','semester':'S'}, {'$and':[{'course':'C'},{'semester':'S'}]}), ({'course':'C','semester':'S','subject':'ML'}, {'$and':[{'course':'C'},{'semester':'S'},{'subject':'ML'}]}), ({'course':'C','semester':'S','subject':'ML','unit':'U'}, {'$and':[{'course':'C'},{'semester':'S'},{'subject':'ML'},{'unit':'U'}]}), ({'material_id':'material-A'}, {'material_id':'material-A'}), ({'course':'C','semester':'S','subject':'ML','unit':'U','material_id':'material-A'}, {'$and':[{'course':'C'},{'semester':'S'},{'subject':'ML'},{'unit':'U'},{'material_id':'material-A'}]})])
def test_filter_composition(filters, expected):
    assert build_filter(filters) == expected


@pytest.mark.parametrize('filters', [{'unknown':'C'}, {'course':[]}, {'course':''}, {'course':{'$ne':'C'}}, ['C']])
def test_invalid_filters(filters):
    with pytest.raises(RetrievalError): build_filter(filters)


def test_unicode_special_filters():
    assert build_filter({'course':'  講義 & ML / 2026  ', 'unit':'Unit “α”'}) == {'$and':[{'course':'講義 & ML / 2026'},{'unit':'Unit “α”'}]}
    assert build_filter({'course':None}) is None


@pytest.mark.parametrize('scope,expected', [({}, 2), ({'course':'C'}, 2), ({'course':'C','semester':'S'}, 1), ({'unit':'Legacy Unit'}, 1), ({'material_id':'material-A'}, 1), ({'subject':'Other'}, 0)])
def test_managed_legacy_scope(scope, expected):
    collection = Collection([row('legacy', 'Legacy PCA text', metadata={'source':'PCA','course':'C','unit':'Legacy Unit'}), row('managed', 'Managed PCA text', metadata=managed())])
    result = retrieve_evidence('PCA', scope, collection=collection)
    assert len(result.evidence) == expected
    if scope.get('semester') or scope.get('material_id'):
        assert all(chunk.material_id for chunk in result.evidence)


def test_candidate_final_and_ranking():
    collection = Collection([row(str(i), f'Distinct evidence number {i}', i/100) for i in range(20,0,-1)])
    result = retrieve_evidence('Question', collection=collection)
    assert collection.calls[0]['n_results'] == 15
    assert [chunk.distance for chunk in result.evidence] == [.01,.02,.03,.04,.05]
    assert result.diagnostics.candidates_returned == 15 and result.diagnostics.evidence_used == 5


def test_relevance_gate_and_diagnostics():
    collection = Collection([row('good','Relevant text',.2), row('boundary','At cutoff',.65), row('bad','Unrelated text',.9)])
    result = retrieve_evidence('Question', {'course':None}, collection=collection)
    assert [chunk.chunk_id for chunk in result.evidence] == ['good','boundary']
    assert result.diagnostics.relevance_rejected == 1
    diagnostics = result.diagnostics.to_dict()
    assert diagnostics['metric'] == 'cosine' and diagnostics['max_distance'] == .65
    assert 'Question' not in str(diagnostics) and 'Relevant text' not in str(diagnostics)


def test_exact_deduplication_and_distinct_overlap():
    shared = 'Shared academic vocabulary about principal components and variance. '
    collection = Collection([row('same', shared+'Unique evidence A',.1), row('same', 'Duplicated ID',.2), row('copy', shared+'Unique   evidence A',.3), row('other', shared+'Unique evidence B',.4)])
    result = retrieve_evidence('Question', collection=collection)
    assert [chunk.chunk_id for chunk in result.evidence] == ['same','other']
    assert result.diagnostics.duplicates_removed == 2


def test_case_sensitive_evidence_not_removed():
    result = retrieve_evidence('Question', collection=Collection([row('a','Variable X is positive.'),row('b','Variable x is positive.')]))
    assert len(result.evidence) == 2


def test_nearest_duplicate_retained_when_adapter_unordered():
    collection = Collection([row()])
    collection.query = Mock(return_value={'ids':[['same','same']], 'documents':[['Less relevant','Most relevant']], 'distances':[[.9,.2]], 'metadatas':[[None,None]]})
    result = retrieve_evidence('Question', collection=collection)
    assert result.evidence[0].text == 'Most relevant'


@pytest.mark.parametrize('rows', [[], [row(distance=.9)]])
def test_empty_and_irrelevant(rows):
    result = retrieve_evidence('Question', collection=Collection(rows))
    assert result.status == 'no_evidence' and not result.sources


def test_empty_collection_skips_embedding():
    collection = Collection();collection.query = Mock(side_effect=AssertionError('No query for empty collection'))
    assert retrieve_evidence('Question', collection=collection).diagnostics.candidates_returned == 0
    collection.query.assert_not_called()


@pytest.mark.parametrize('metadata', [None, {}, [], {'source':42,'unit':False}, {'source':'講義.png','unit':'Unit α','page':9}, {'source':'notes.pdf','page':True}, {'source':'OCR notice','content_type':'image/png','page':9}])
def test_missing_malformed_and_ocr_metadata(metadata):
    result = retrieve_evidence('Question', collection=Collection([row(text='Unicode 講義 résumé',metadata=metadata)]))
    chunk = result.evidence[0]
    assert chunk.text == 'Unicode 講義 résumé'
    assert chunk.page is None
    if isinstance(metadata,dict) and metadata.get('source') == '講義.png':
        assert chunk.content_type == 'Image/OCR'


@pytest.mark.parametrize('distance', [None, '0.2', True, float('nan'), float('inf'), -1, 3])
def test_invalid_distance_rejected(distance):
    raw = {'ids':[['c']], 'documents':[['text']], 'distances':[[distance]], 'metadatas':[[{}]]}
    chunks, invalid, returned = normalize_results(raw)
    assert not chunks and invalid == returned == 1


@pytest.mark.parametrize('raw', [None, {}, {'ids':[[]],'documents':[[]]}, {'ids':[['a']],'documents':[[]],'distances':[[]]}, {'ids':[['a']],'documents':[['text']],'distances':[[.2]],'metadatas':[[{},{}]]}])
def test_malformed_result_controlled(raw):
    collection=Collection([row()]);collection.query=Mock(return_value=raw)
    with pytest.raises(RetrievalError): retrieve_evidence('Question',collection=collection)


@pytest.mark.parametrize('metric', ['l2','ip',None])
def test_wrong_metric_never_uses_cosine_threshold(metric):
    collection = Collection([row()]);collection.configuration={'hnsw':{'space':metric}}
    with pytest.raises(RetrievalError): retrieve_evidence('Question',collection=collection)
    assert not collection.calls


def test_client_failure_controlled():
    collection=Collection([row()]);collection.query=Mock(side_effect=RuntimeError('internal client detail'))
    with pytest.raises(RetrievalError, match='retrieval failed') as error: retrieve_evidence('Question',collection=collection)
    assert isinstance(error.value.__cause__,RuntimeError)


@pytest.mark.parametrize('question', ['', ' ', None, 42])
def test_invalid_question(question):
    with pytest.raises(RetrievalError): retrieve_evidence(question,collection=Collection())
