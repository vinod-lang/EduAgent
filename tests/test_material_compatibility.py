import ast
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
import db
from test_material_identity import storage, hierarchy, upload


@pytest.mark.parametrize('metadata',[{'source':'PCA','unit':'Legacy Unit'}, {'material_id':'synthetic-uuid','source':'New Notes.pdf','course':'C','semester':'S','subject':'Subject','unit':'U'}])
def test_agents_metadata(agents,monkeypatch,mcq,metadata):
    vectors=agents['vectors']
    vectors.search_database.return_value={'documents':[['Synthetic PCA']], 'metadatas':[[metadata]]}
    vectors.get_all_chunks.return_value=(['Synthetic PCA'],[metadata])
    monkeypatch.setattr(agents['student_support_agent'].ollama,'chat',Mock(return_value={'message':{'content':'Synthetic answer'}}))
    assert metadata['source'] in agents['student_support_agent'].answer_question('Question',course='C')[1][0]
    monkeypatch.setattr(agents['assessment_agent'].ollama,'chat',Mock(return_value={'message':{'content':json.dumps([mcq])}}))
    assert metadata['source'] in agents['assessment_agent'].generate_questions(source_name=metadata['source'],course='C',num_questions=1)[0]['source_label']
    vectors.get_all_chunks.assert_called_once_with(source_name=metadata['source'],course='C')


def test_vector_exact_apis():
    # Execute only API functions: never import the real embedding/client globals.
    tree=ast.parse((Path(__file__).resolve().parents[1]/'vector_store.py').read_text())
    names={'get_all_chunks','add_material_chunks','get_material_chunks','delete_material_chunks','update_material_chunks'}
    module=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[])
    collection=Mock();collection.get.return_value={'documents':['synthetic'],'metadatas':[{'source':'PCA'}]}
    env={'collection':collection};exec(compile(module,'vector_store.py','exec'),env)
    env['get_all_chunks']('PCA','C')
    assert collection.get.call_args.kwargs['where']=={'$and':[{'source':'PCA'},{'course':'C'}]}
    env['add_material_chunks'](['uuid_chunk_0'],['text'],{'material_id':'uuid'})
    collection.add.assert_called_once_with(ids=['uuid_chunk_0'],documents=['text'],metadatas=[{'material_id':'uuid'}])
    env['delete_material_chunks'](['uuid_chunk_0']);collection.delete.assert_called_once_with(ids=['uuid_chunk_0'])
    env['update_material_chunks'](['uuid_chunk_0'],[{'unit':'U'}]);collection.update.assert_called_once_with(ids=['uuid_chunk_0'],metadatas=[{'unit':'U'}])


def test_management_ui(storage,hierarchy,agents,monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    m=upload(storage,hierarchy)['material']
    db.add_document_record('PCA',hierarchy['course'],None,'PCA.pdf')
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
    app.sidebar.radio[0].set_value('Upload Content').run()
    assert not app.exception
    assert {'Semester:','Subject:','Unit:'}.issubset({item.label for item in app.text_input})
    next(b for b in app.button if b.label=='Add to Database').click().run()
    assert not app.exception and any('Choose a PDF' in item.value for item in app.warning)
    app.sidebar.radio[0].set_value('Courses & Activity').run()
    assert not app.exception
    assert any('Legacy material' in item.value for item in app.caption)
    assert any('notes.pdf' in item.value for item in app.markdown)
    assert any('Confirm permanent deletion'==item.label for item in app.checkbox)


def test_ui_edit_and_delete(storage,hierarchy,agents,monkeypatch,tmp_path):
    import material_service as service
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(service,'vectors_api',lambda _:storage[1])
    m=upload(storage,hierarchy)['material']
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
    app.sidebar.radio[0].set_value('Courses & Activity').run()
    next(i for i in app.text_input if i.label=='Unit').set_value('Unit Edited')
    next(b for b in app.button if b.label=='Save hierarchy').click().run()
    assert not app.exception and db.get_material(m['material_id'])['unit']=='Unit Edited'
    assert any('Unit Edited' in row.value for row in app.markdown)
    next(c for c in app.checkbox if c.label=='Confirm permanent deletion').check().run()
    next(b for b in app.button if b.label=='Delete material').click().run()
    assert not app.exception and db.get_material(m['material_id']) is None
    assert not storage[1].rows and not (storage[0]/m['managed_filename']).exists()
    assert any('Material deleted' in item.value for item in app.success)
