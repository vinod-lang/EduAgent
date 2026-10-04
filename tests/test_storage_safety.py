"""Fresh-process import guards and exact lazy/injected storage API tests."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import Mock
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('names',[
 ['vector_store'],['assessment_agent'],['student_support_agent'],['assessment_studio'],
 ['vector_store','assessment_agent','student_support_agent','assessment_studio','assessment_ui','coordinator','document_studio','document_ui','document_repository','document_diff','document_preferences','document_feedback_ui']])
def test_imports_never_initialize_storage_or_model(tmp_path,names):
    target=tmp_path/'chroma_db';target.mkdir();sentinel=target/'chroma.sqlite3';sentinel.write_bytes(b'isolated sentinel - not a real database')
    before=sentinel.read_bytes()
    script="""
import importlib,sys,types
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
def forbidden(*args,**kwargs):
    raise AssertionError('Import attempted Chroma/client/collection/model initialization')
chroma=types.ModuleType('chromadb');chroma.PersistentClient=forbidden
utils=types.ModuleType('chromadb.utils');embeddings=types.ModuleType('chromadb.utils.embedding_functions')
embeddings.SentenceTransformerEmbeddingFunction=forbidden
utils.embedding_functions=embeddings;chroma.utils=utils
sys.modules.update({'chromadb':chroma,'chromadb.utils':utils,'chromadb.utils.embedding_functions':embeddings})
for name in sys.argv[2:]:importlib.import_module(name)
import vector_store
assert not vector_store._clients and not vector_store._collections
assert vector_store._embedding_function is None
assert not hasattr(vector_store,'collection') and not hasattr(vector_store,'client')
"""
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',EDUAGENT_CHROMA_PATH=str(target))
    result=subprocess.run([sys.executable,'-c',script,str(ROOT),*names],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert sentinel.read_bytes()==before and list(target.iterdir())==[sentinel]

@pytest.fixture
def store(monkeypatch):
    spec=importlib.util.spec_from_file_location('isolated_vector_store',ROOT/'vector_store.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    client=Mock();collection=Mock();client.get_or_create_collection.return_value=collection
    chroma=types.ModuleType('chromadb');chroma.PersistentClient=Mock(return_value=client)
    embeddings=types.ModuleType('chromadb.utils.embedding_functions');embeddings.SentenceTransformerEmbeddingFunction=Mock(return_value=object())
    utils=types.ModuleType('chromadb.utils');utils.embedding_functions=embeddings;chroma.utils=utils
    monkeypatch.setitem(sys.modules,'chromadb',chroma)
    monkeypatch.setitem(sys.modules,'chromadb.utils',utils)
    monkeypatch.setitem(sys.modules,'chromadb.utils.embedding_functions',embeddings)
    return module,chroma,embeddings,client,collection


def test_first_explicit_use_is_cached_per_path(store,tmp_path):
    module,chroma,embeddings,client,collection=store
    assert not module._clients and not module._collections
    assert module.get_collection(tmp_path/'a') is collection
    assert module.get_collection(tmp_path/'a') is collection
    chroma.PersistentClient.assert_called_once_with(path=str((tmp_path/'a').resolve()))
    client.get_or_create_collection.assert_called_once()
    embeddings.SentenceTransformerEmbeddingFunction.assert_called_once_with(model_name='all-MiniLM-L6-v2')
    module.get_collection(tmp_path/'b')
    assert chroma.PersistentClient.call_count==2 and client.get_or_create_collection.call_count==2
    assert embeddings.SentenceTransformerEmbeddingFunction.call_count==1


def test_environment_and_explicit_path_precedence(store,tmp_path,monkeypatch):
    module,chroma,_,_,_=store
    monkeypatch.setenv('EDUAGENT_CHROMA_PATH',str(tmp_path/'env'))
    module.get_chroma_client();module.get_chroma_client(tmp_path/'explicit')
    assert [c.kwargs['path'] for c in chroma.PersistentClient.call_args_list]==[str(tmp_path/'env'),str(tmp_path/'explicit')]


def test_relative_paths_do_not_share_cache_across_cwd(store,tmp_path,monkeypatch):
    module,chroma,_,_,_=store
    a=tmp_path/'a';b=tmp_path/'b';a.mkdir();b.mkdir()
    monkeypatch.chdir(a);module.get_chroma_client('chroma_db')
    monkeypatch.chdir(b);module.get_chroma_client('chroma_db')
    assert chroma.PersistentClient.call_count==2


def test_injected_client_and_embedding_never_open_default(store):
    module,chroma,embeddings,_,_=store
    supplied=Mock();function=object()
    assert module.get_collection(client=supplied,embedding_function=function) is supplied.get_or_create_collection.return_value
    supplied.get_or_create_collection.assert_called_once_with(name='course_material',embedding_function=function)
    chroma.PersistentClient.assert_not_called();embeddings.SentenceTransformerEmbeddingFunction.assert_not_called()


def test_explicit_client_without_model_does_not_load_embedding(store,tmp_path):
    module,_,embeddings,_,_=store
    module.get_chroma_client(tmp_path/'isolated')
    embeddings.SentenceTransformerEmbeddingFunction.assert_not_called()


def test_failed_model_init_does_not_open_database(store,tmp_path):
    module,chroma,embeddings,_,_=store
    embeddings.SentenceTransformerEmbeddingFunction.side_effect=RuntimeError('synthetic model failure')
    with pytest.raises(RuntimeError):module.get_collection(tmp_path/'isolated')
    chroma.PersistentClient.assert_not_called()
    assert not module._collections and not module._clients

@pytest.mark.parametrize('path',['', ' ', 123])
def test_invalid_path(store,path):
    with pytest.raises(ValueError):store[0].get_chroma_client(path)
    store[1].PersistentClient.assert_not_called()


def test_collection_injection_preserves_exact_operations(store):
    module,chroma,embeddings,_,_=store
    supplied=Mock();supplied.get.return_value={'documents':['text'],'metadatas':[{'unit':'U'}]}
    module.add_material_chunks(['a'],['text'],{'material_id':'id'},collection=supplied)
    supplied.add.assert_called_once_with(ids=['a'],documents=['text'],metadatas=[{'material_id':'id'}])
    module.get_material_chunks(['a'],collection=supplied);supplied.get.assert_called_with(ids=['a'])
    module.delete_material_chunks(['a'],collection=supplied);supplied.delete.assert_called_once_with(ids=['a'])
    module.update_material_chunks(['b'],[{'unit':'U'}],collection=supplied);supplied.update.assert_called_once_with(ids=['b'],metadatas=[{'unit':'U'}])
    assert module.get_all_chunks('PCA','C',collection=supplied)==(['text'],[{'unit':'U'}])
    assert supplied.get.call_args.kwargs==dict(where={'$and':[{'course':'C'},{'source':'PCA'}]},limit=15)
    module.search_database('Question',course='C',unit='U',collection=supplied)
    assert supplied.query.call_args.kwargs['where']=={'$and':[{'course':'C'},{'unit':'U'}]}
    chroma.PersistentClient.assert_not_called();embeddings.SentenceTransformerEmbeddingFunction.assert_not_called()


def test_empty_delete_update_do_not_open_storage(store):
    module,chroma,embeddings,_,_=store
    module.delete_material_chunks([]);module.update_material_chunks([],[])
    chroma.PersistentClient.assert_not_called();embeddings.SentenceTransformerEmbeddingFunction.assert_not_called()


def test_collection_failure_is_not_cached(store,tmp_path):
    module,_,_,client,collection=store
    client.get_or_create_collection.side_effect=[RuntimeError('synthetic collection failure'),collection]
    with pytest.raises(RuntimeError):module.get_collection(tmp_path/'isolated')
    assert not module._collections
    assert module.get_collection(tmp_path/'isolated') is collection


def test_suite_isolation_and_sentinel_before_collection():
    import conftest
    assert os.environ['HF_HUB_OFFLINE']=='1' and os.environ['TRANSFORMERS_OFFLINE']=='1'
    assert Path(os.environ['EDUAGENT_CHROMA_PATH']).resolve()!=ROOT/'chroma_db'
    assert conftest.runtime_inventory()==conftest._RUNTIME_BEFORE
    assert Path(conftest.db.DB_PATH).resolve()!=ROOT/'eduagent.db'


def test_runtime_sentinel_reports_mutation(monkeypatch):
    # Test the guard itself without changing a real file or running cleanup.
    import conftest
    from types import SimpleNamespace
    reporter=Mock()
    storage_path=os.environ['EDUAGENT_CHROMA_PATH']
    monkeypatch.setenv('EDUAGENT_CHROMA_PATH',storage_path)
    monkeypatch.setattr(conftest.db,'DB_PATH',conftest.db.DB_PATH)
    session=SimpleNamespace(config=SimpleNamespace(pluginmanager=SimpleNamespace(get_plugin=lambda _:reporter)),exitstatus=0)
    monkeypatch.setattr(conftest,'runtime_inventory',lambda:{'synthetic new file':(1,'hash')})
    monkeypatch.setattr(conftest,'_TEST_STORAGE',SimpleNamespace(cleanup=lambda:None))
    conftest.pytest_sessionfinish(session,0)
    assert session.exitstatus==pytest.ExitCode.TESTS_FAILED
    reporter.write_line.assert_called_once()
    # Restore the suite's isolated path after exercising the mocked hook.
    os.environ['EDUAGENT_CHROMA_PATH']=storage_path
