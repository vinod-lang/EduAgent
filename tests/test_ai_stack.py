"""Build 17 profile/availability contracts; no live Ollama or downloads."""
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import MagicMock,Mock
import pytest
import httpx
import config
import ai_provider as ai
from generation_diagnostics import annotate,from_error
from document_models import DocumentDraft

@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    import os
    for key in list(os.environ):
        if key.startswith('EDUAGENT_LLM_') or key.startswith('EDUAGENT_RAG_') or key in ('EDUAGENT_EMBEDDING_MODEL','EDUAGENT_ROUTER_ENABLED','EDUAGENT_RERANKER_ENABLED','OLLAMA_HOST','EDUAGENT_OLLAMA_BASE_URL'):
            monkeypatch.delenv(key,raising=False)
    ai.clear_generation_selection()

@pytest.fixture
def client(monkeypatch):
    client=MagicMock();client.__enter__.return_value=client
    client.chat.return_value={'message':{'content':'Synthetic accepted response'}}
    monkeypatch.setattr(ai.ollama,'Client',Mock(return_value=client))
    return client


def inventory(client,*models):
    client.list.return_value={'models':[{'model':name} for name in models]}


def test_profile_defaults():
    p=config.get_ai_profile()
    assert (p.provider,p.preferred_model,p.fallback_model,p.embedding_model)==('ollama','qwen2.5:3b','llama3.2:3b','all-MiniLM-L6-v2')
    assert (p.candidate_k,p.final_k,p.distance_threshold,p.reranker_enabled,p.router_enabled)==(15,5,.50,False,False)

@pytest.mark.parametrize('key,value,field,expected',[
 ('EDUAGENT_LLM_MODEL','local-reviewed','preferred_model','local-reviewed'),
 ('EDUAGENT_LLM_PREFERRED_MODEL','reviewed-preferred','preferred_model','reviewed-preferred'),
 ('EDUAGENT_LLM_FALLBACK_MODEL','reviewed-fallback','fallback_model','reviewed-fallback'),
 ('EDUAGENT_LLM_FALLBACK_MODEL','none','fallback_model',None),
 ('EDUAGENT_RAG_DISTANCE_THRESHOLD','0.65','distance_threshold',.65),
 ('EDUAGENT_RAG_MAX_DISTANCE','0.4','distance_threshold',.4),
 ('EDUAGENT_RAG_CANDIDATE_K','20','candidate_k',20),
 ('EDUAGENT_RAG_FINAL_K','4','final_k',4),
 ('EDUAGENT_EMBEDDING_MODEL','all-MiniLM-L6-v2','embedding_model','all-MiniLM-L6-v2')])
def test_profile_overrides(monkeypatch,key,value,field,expected):
    monkeypatch.setenv(key,value);assert getattr(config.get_ai_profile(),field)==expected


def test_precedence(monkeypatch):
    monkeypatch.setenv('EDUAGENT_LLM_MODEL','old-name');monkeypatch.setenv('EDUAGENT_LLM_PREFERRED_MODEL','new-name')
    monkeypatch.setenv('EDUAGENT_RAG_MAX_DISTANCE','.65');monkeypatch.setenv('EDUAGENT_RAG_DISTANCE_THRESHOLD','.4')
    p=config.get_ai_profile();assert p.preferred_model=='new-name' and p.distance_threshold==.4

@pytest.mark.parametrize('key,value',[
 ('EDUAGENT_LLM_PREFERRED_MODEL',' '),('EDUAGENT_LLM_FALLBACK_MODEL',' '),('EDUAGENT_LLM_PROVIDER','cloud'),
 ('EDUAGENT_RAG_DISTANCE_THRESHOLD','nan'),('EDUAGENT_RAG_DISTANCE_THRESHOLD','inf'),('EDUAGENT_RAG_DISTANCE_THRESHOLD','-1'),('EDUAGENT_RAG_DISTANCE_THRESHOLD','2.1'),('EDUAGENT_RAG_DISTANCE_THRESHOLD','bad'),('EDUAGENT_RAG_DISTANCE_THRESHOLD',''),
 ('EDUAGENT_RAG_CANDIDATE_K','4'),('EDUAGENT_RAG_FINAL_K','16'),
 ('EDUAGENT_RERANKER_ENABLED','true'),('EDUAGENT_ROUTER_ENABLED','true'),('EDUAGENT_ROUTER_ENABLED','garbage'),
 ('EDUAGENT_EMBEDDING_MODEL','different-model')])
def test_invalid_profile(monkeypatch,key,value):
    monkeypatch.setenv(key,value)
    with pytest.raises(config.ConfigurationError):config.get_ai_profile()

@pytest.mark.parametrize('models,effective,fallback',[
 (('qwen2.5:3b','llama3.2:3b'),'qwen2.5:3b',False),
 (('qwen2.5:3b',),'qwen2.5:3b',False),
 (('llama3.2:3b',),'llama3.2:3b',True)])
def test_selection(client,models,effective,fallback):
    inventory(client,*models)
    result=ai.generate_chat_measured([{'role':'user','content':'Synthetic'}])
    assert result.effective_model==effective and result.fallback_active is fallback
    client.chat.assert_called_once_with(model=effective,messages=[{'role':'user','content':'Synthetic'}])
    client.pull.assert_not_called();client.create.assert_not_called();client.delete.assert_not_called()


def test_none_available_safe_error_no_generation(client):
    inventory(client,'unrelated')
    with pytest.raises(ai.AIProviderError,match='will not download') as error:ai.generate_chat([{'role':'user','content':'PRIVATE synthetic prompt'}])
    client.chat.assert_not_called();client.pull.assert_not_called()
    assert 'PRIVATE' not in str(from_error(error.value))
    assert ai.get_last_generation_selection() is None


def test_fallback_disabled(client,monkeypatch):
    inventory(client,'llama3.2:3b');monkeypatch.setenv('EDUAGENT_LLM_FALLBACK_MODEL','none')
    with pytest.raises(ai.AIProviderError):ai.generate_chat([{'role':'user','content':'Synthetic'}])
    client.chat.assert_not_called()


def test_inventory_failure_no_blind_fallback(client):
    client.list.side_effect=httpx.ConnectError('PRIVATE server error')
    with pytest.raises(ai.AIConnectionError):ai.generate_chat([{'role':'user','content':'Synthetic'}])
    client.chat.assert_not_called();client.pull.assert_not_called()

@pytest.mark.parametrize('response',[None,{}, {'models':None},{'models':'bad'},{'models':[{}]},{'models':[{'model':7}]}])
def test_inventory_malformed(client,response):
    client.list.return_value=response
    with pytest.raises(ai.AIResponseError):ai.generate_chat([{'role':'user','content':'Synthetic'}])
    client.chat.assert_not_called()


def test_inventory_object_response_and_latest_alias(client,monkeypatch):
    client.list.return_value=SimpleNamespace(models=[SimpleNamespace(model='reviewed:latest')])
    monkeypatch.setenv('EDUAGENT_LLM_MODEL','reviewed')
    assert ai.generate_chat([{'role':'user','content':'Synthetic'}])
    assert client.chat.call_args.kwargs['model']=='reviewed'


def test_selected_model_failure_does_not_retry_fallback(client):
    inventory(client,'qwen2.5:3b','llama3.2:3b');client.chat.side_effect=RuntimeError('PRIVATE')
    with pytest.raises(ai.AIProviderError):ai.generate_chat([{'role':'user','content':'Synthetic'}])
    assert client.chat.call_count==1 and client.chat.call_args.kwargs['model']=='qwen2.5:3b'


def test_explicit_override_never_falls_back(client):
    ai.generate_chat([{'role':'user','content':'Synthetic'}],model='explicit-benchmark-model')
    client.list.assert_not_called();assert client.chat.call_args.kwargs['model']=='explicit-benchmark-model'


def test_effective_model_provenance(client):
    inventory(client,'llama3.2:3b');ai.generate_chat([{'role':'user','content':'Synthetic'}])
    draft=annotate(DocumentDraft('notice',body=('Synthetic',)),'document',1)
    assert draft.provenance.model=='llama3.2:3b' and draft.provenance.fallback_active
    assert 'model' not in draft.to_dict()


def test_status_inventory_only_and_private(client):
    inventory(client,'llama3.2:3b')
    status=ai.get_ai_stack_status()
    assert status.preferred_model=='qwen2.5:3b' and status.effective_model=='llama3.2:3b' and status.fallback_active
    assert status.embedding_model=='all-MiniLM-L6-v2' and status.distance_threshold==.50
    text=str(asdict(status));assert '/Users' not in text and 'http://' not in text
    client.chat.assert_not_called();client.pull.assert_not_called()


def test_failed_generation_clears_prior_selection(client):
    inventory(client,'llama3.2:3b');ai.generate_chat([{'role':'user','content':'Synthetic'}])
    inventory(client)
    with pytest.raises(ai.AIProviderError):ai.generate_chat([{'role':'user','content':'Synthetic'}])
    assert ai.get_last_generation_selection() is None
