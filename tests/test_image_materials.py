import ast
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
import pytesseract
import db
import material_service as service
from test_material_identity import storage, hierarchy
from test_content_ingestion import image_bytes


def ingest(storage, hierarchy, data=None, name='lecture.png'):
    return service.upload_material(data or image_bytes(), name, hierarchy, uploads=storage[0], vectors=storage[1])


@pytest.mark.parametrize('name,format', [('lecture.png', 'PNG'), ('lecture.jpg', 'JPEG'), ('lecture.jpeg', 'JPEG'), ('LECTURE.PNG', 'PNG')])
def test_image_lifecycle(storage, hierarchy, monkeypatch, name, format):
    ocr = Mock(return_value='Synthetic PCA preserves variance. ' * 40)
    monkeypatch.setattr(pytesseract, 'image_to_string', ocr)
    data = image_bytes(format); out = ingest(storage, hierarchy, data, name)
    assert out['success'], out
    record = out['material']; identity = record['material_id']; ids = json.loads(record['chunk_ids'])
    assert record['file_hash'] == hashlib.sha256(data).hexdigest()
    assert record['managed_filename'] == identity + Path(name).suffix.lower()
    assert ids == [f'{identity}_chunk_{i}' for i in range(len(ids))]
    assert len(out['text_preview']) <= 1000 and 'PCA' in out['text_preview']
    assert all(row['metadata'] == dict(material_id=identity, source=name, **hierarchy) for row in storage[1].rows.values())
    changed = dict(hierarchy, course='Synthetic Course 2', unit='Unit 2')
    assert service.edit_hierarchy(identity, changed, vectors=storage[1])['success']
    assert db.get_material(identity)['unit'] == 'Unit 2'
    assert all(row['metadata']['course'] == changed['course'] for row in storage[1].rows.values())
    assert db.get_material(identity)['file_hash'] == record['file_hash']
    assert (storage[0]/record['managed_filename']).read_bytes() == data
    assert ocr.call_count == 1
    deletion = service.delete_material(identity, uploads=storage[0], vectors=storage[1])
    assert deletion['success'] and deletion['vectors_deleted'] == len(ids) and deletion['file_deleted']
    assert db.get_material(identity) is None and not storage[1].rows
    assert not (storage[0]/record['managed_filename']).exists()


@pytest.mark.parametrize('text', ['', '   \n\t  '])
def test_empty_ocr_rolls_back(storage, hierarchy, monkeypatch, text):
    monkeypatch.setattr(pytesseract, 'image_to_string', Mock(return_value=text))
    out = ingest(storage, hierarchy)
    assert not out['success'] and 'no usable' in out['error']
    assert not db.list_materials() and not storage[1].rows and not list(storage[0].iterdir())


@pytest.mark.parametrize('failure', [pytesseract.TesseractNotFoundError(), RuntimeError('synthetic OCR failure')])
def test_ocr_failure_rolls_back(storage, hierarchy, monkeypatch, failure):
    monkeypatch.setattr(pytesseract, 'image_to_string', Mock(side_effect=failure))
    out = ingest(storage, hierarchy)
    assert not out['success'] and not out['warnings']
    assert not db.list_materials() and not storage[1].rows and not list(storage[0].iterdir())


def test_invalid_image_rolls_back(storage, hierarchy):
    out = ingest(storage, hierarchy, b'invalid image')
    assert not out['success'] and 'corrupt' in out['error']
    assert not db.list_materials() and not storage[1].rows and not list(storage[0].iterdir())


def test_byte_identity_and_unrelated_ownership(storage, hierarchy, monkeypatch):
    ocr = Mock(return_value='Identical OCR text does not establish byte identity.')
    monkeypatch.setattr(pytesseract, 'image_to_string', ocr)
    a = ingest(storage, hierarchy)['material']
    before = dict(storage[1].rows)
    duplicate = ingest(storage, hierarchy, name='renamed.png')
    assert duplicate['duplicate'] and duplicate['existing_material']['material_id'] == a['material_id']
    assert storage[1].rows == before and ocr.call_count == 1
    b = ingest(storage, hierarchy, image_bytes(color='black'))['material']
    assert a['material_id'] != b['material_id'] and a['file_hash'] != b['file_hash']
    assert not set(json.loads(a['chunk_ids'])) & set(json.loads(b['chunk_ids']))
    assert service.delete_material(a['material_id'], uploads=storage[0], vectors=storage[1])['success']
    assert set(storage[1].rows) == set(json.loads(b['chunk_ids']))
    assert db.get_material(b['material_id']) and (storage[0]/b['managed_filename']).exists()


def test_size_check_before_extraction_or_storage(storage, hierarchy, monkeypatch):
    monkeypatch.setenv('EDUAGENT_MAX_UPLOAD_MB', '0.000001')
    ocr = Mock(); monkeypatch.setattr(pytesseract, 'image_to_string', ocr)
    with pytest.raises(service.MaterialError, match='size limit'): ingest(storage, hierarchy)
    assert not storage[0].exists() and not db.list_materials() and not storage[1].rows
    ocr.assert_not_called()


def test_unsafe_image_managed_path(storage, hierarchy, monkeypatch, tmp_path):
    monkeypatch.setattr(pytesseract, 'image_to_string', Mock(return_value='PCA synthetic content'))
    record = ingest(storage, hierarchy)['material']
    outside = tmp_path / 'outside.png'; outside.write_bytes(b'keep')
    with db.material_connection() as conn:
        conn.execute('UPDATE materials SET managed_filename=? WHERE material_id=?', (str(outside), record['material_id']))
    out = service.delete_material(record['material_id'], uploads=storage[0], vectors=storage[1])
    assert not out['success'] and outside.read_bytes() == b'keep'
    assert db.get_material(record['material_id']) and storage[1].rows


def test_ocr_retrieval_qa_and_assessment(storage, hierarchy, monkeypatch, agents, mcq):
    # Run CURRENT retrieval functions with only the collection boundary substituted.
    monkeypatch.setattr(pytesseract, 'image_to_string', Mock(return_value='PCA preserves variance in fewer dimensions.'))
    material = ingest(storage, hierarchy)['material']
    class Collection:
        def matching(self, where):
            clauses = where.get('$and', [where]) if where else []
            return [r for r in storage[1].rows.values() if all(all(r['metadata'].get(k) == v for k, v in clause.items()) for clause in clauses)]
        def query(self, query_texts, n_results, where):
            rows = self.matching(where)[:n_results]
            return {'documents': [[r['document'] for r in rows]], 'metadatas': [[r['metadata'] for r in rows]]}
        def get(self, where=None, limit=15):
            rows = self.matching(where)[:limit]
            return {'documents': [r['document'] for r in rows], 'metadatas': [r['metadata'] for r in rows]}
    tree = ast.parse((Path(__file__).resolve().parents[1]/'vector_store.py').read_text())
    module = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('search_database', 'get_all_chunks')], type_ignores=[])
    env = {'collection': Collection()}; exec(compile(module, 'vector_store.py', 'exec'), env)
    qa = agents['student_support_agent']; assessment = agents['assessment_agent']
    monkeypatch.setattr(qa, 'search_database', env['search_database'])
    monkeypatch.setattr(assessment, 'get_all_chunks', env['get_all_chunks'])
    assert env['search_database']('PCA', course='Other Course')['documents'] == [[]]
    provider = Mock(return_value='PCA preserves variance.'); monkeypatch.setattr(qa.ai_provider, 'generate_chat', provider)
    answer, sources = qa.answer_question('What does PCA preserve?', course=hierarchy['course'])
    assert answer == 'PCA preserves variance.' and 'lecture.png' in sources[0]
    assert 'PCA preserves variance in fewer dimensions.' in provider.call_args.kwargs['messages'][1]['content']
    assert qa.answer_question('PCA', course='Other Course')[1] == []
    provider.return_value = json.dumps([mcq])
    questions = assessment.generate_questions(source_name=material['original_filename'], course=hierarchy['course'], num_questions=1)
    assert 'lecture.png' in questions[0]['source_label']
    assert 'PCA preserves variance' in provider.call_args.kwargs['messages'][1]['content']
    assert assessment.generate_questions(source_name='other.png', course=hierarchy['course'], num_questions=1) is None
    provider.side_effect = [json.dumps([mcq]), json.dumps([{'question': 'Explain PCA.', 'model_answer': 'PCA preserves variance.', 'source_chunk': 0}])]
    paper = assessment.generate_question_paper(source_name=material['original_filename'], course=hierarchy['course'], num_mcq=1, num_descriptive=1)
    assert paper['total_marks'] == 7
    assert 'lecture.png' in paper['mcq_section'][0]['source_label']
    assert 'lecture.png' in paper['descriptive_section'][0]['source_label']


@pytest.mark.parametrize('failure', ['vectors', 'registry'])
def test_image_storage_failure_rollback(storage, hierarchy, monkeypatch, failure):
    monkeypatch.setattr(pytesseract, 'image_to_string', Mock(return_value='Synthetic OCR lecture'))
    if failure == 'vectors':
        storage[1].fail_add = True
    else:
        monkeypatch.setattr(db, 'register_material', Mock(side_effect=RuntimeError('synthetic registry failure')))
    out = ingest(storage, hierarchy)
    assert not out['success'] and not out['warnings']
    assert not db.list_materials() and not storage[1].rows and not list(storage[0].iterdir())


def test_pdf_managed_default_extraction(storage, hierarchy, tmp_path, monkeypatch):
    from fpdf import FPDF
    pdf = FPDF(); pdf.add_page(); pdf.set_font('Helvetica', size=12)
    pdf.cell(text='Synthetic PDF academic lecture')
    data = bytes(pdf.output())
    monkeypatch.setattr(pytesseract, 'image_to_string', Mock(side_effect=AssertionError('PDF must not call OCR')))
    out = ingest(storage, hierarchy, data, 'lecture.PDF')
    assert out['success'] and out['material']['managed_filename'].endswith('.pdf')
    assert not out['text_preview']
    assert any('--- Page 1 ---' in row['document'] for row in storage[1].rows.values())
    assert service.delete_material(out['material']['material_id'], uploads=storage[0], vectors=storage[1])['success']


def test_failed_ocr_does_not_initialize_vector_client(storage, hierarchy, monkeypatch):
    monkeypatch.setattr(pytesseract, 'image_to_string', Mock(side_effect=pytesseract.TesseractNotFoundError()))
    boundary = Mock(side_effect=AssertionError('Must not initialize indexing for failed extraction'))
    monkeypatch.setattr(service, 'vectors_api', boundary)
    assert not ingest(storage, hierarchy)['success']
    boundary.assert_not_called()
