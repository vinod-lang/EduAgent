from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock
import ast
import httpx
import pytest
import config
import ai_provider as ai

@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ('EDUAGENT_LLM_PROVIDER','EDUAGENT_LLM_PREFERRED_MODEL','EDUAGENT_LLM_FALLBACK_MODEL','EDUAGENT_LLM_MODEL','EDUAGENT_OLLAMA_BASE_URL','EDUAGENT_LLM_TIMEOUT_SECONDS','OLLAMA_HOST'):
        monkeypatch.delenv(key,raising=False)


def test_defaults():
    c=config.get_ai_config()
    assert (c.provider,c.model,c.base_url,c.timeout_seconds)==('ollama','qwen2.5:3b','http://127.0.0.1:11434',120)
    assert ai.get_default_model_name()=='qwen2.5:3b'

@pytest.mark.parametrize('key,value,field,expected',[('EDUAGENT_LLM_MODEL','alternate','model','alternate'),('EDUAGENT_LLM_PROVIDER','ollama','provider','ollama'),('EDUAGENT_OLLAMA_BASE_URL','http://localhost:1234','base_url','http://localhost:1234'),('EDUAGENT_LLM_TIMEOUT_SECONDS','4.5','timeout_seconds',4.5),('OLLAMA_HOST','http://localhost:2345','base_url','http://localhost:2345')])
def test_override(monkeypatch,key,value,field,expected):
    monkeypatch.setenv(key,value);assert getattr(config.get_ai_config(),field)==expected


def test_precedence(monkeypatch):
    monkeypatch.setenv('OLLAMA_HOST','http://localhost:2345');monkeypatch.setenv('EDUAGENT_OLLAMA_BASE_URL','http://localhost:1234')
    assert config.get_ai_config().base_url=='http://localhost:1234'

@pytest.mark.parametrize('key,value',[('EDUAGENT_LLM_PROVIDER','cloud'),('EDUAGENT_LLM_MODEL',' '),('EDUAGENT_LLM_TIMEOUT_SECONDS','bad'),('EDUAGENT_LLM_TIMEOUT_SECONDS','0'),('EDUAGENT_LLM_TIMEOUT_SECONDS','-1'),('EDUAGENT_LLM_TIMEOUT_SECONDS','inf'),('EDUAGENT_LLM_TIMEOUT_SECONDS','nan'),('EDUAGENT_OLLAMA_BASE_URL',''),('EDUAGENT_OLLAMA_BASE_URL','ftp://localhost'),('EDUAGENT_OLLAMA_BASE_URL','http://user:password@localhost')])
def test_invalid_config(monkeypatch,key,value):
    monkeypatch.setenv(key,value)
    with pytest.raises(config.ConfigurationError):config.get_ai_config()
    with pytest.raises(ai.AIProviderError) as error:ai.get_default_model_name()
    assert isinstance(error.value.__cause__,config.ConfigurationError)

@pytest.fixture
def boundary(monkeypatch):
    client=MagicMock();client.__enter__.return_value=client;client.chat.return_value={'message':{'content':'Synthetic output'}}
    client.list.side_effect=lambda: {'models':[{'model':ai.configured().model}]}
    factory=Mock(return_value=client);monkeypatch.setattr(ai.ollama,'Client',factory)
    return client,factory


def test_forwarding(boundary,monkeypatch):
    client,factory=boundary;monkeypatch.setenv('EDUAGENT_LLM_MODEL','configured');monkeypatch.setenv('EDUAGENT_LLM_TIMEOUT_SECONDS','8')
    messages=[{'role':'system','content':'System instructions'},{'role':'user','content':'Question'}]
    assert ai.generate_chat(messages)=='Synthetic output'
    factory.assert_called_once_with(host='http://127.0.0.1:11434',timeout=8)
    client.chat.assert_called_once_with(model='configured',messages=messages)
    client.__exit__.assert_called_once()
    ai.generate_chat(messages,model='override');assert client.chat.call_args.kwargs['model']=='override'
    assert ai.get_default_model_name()=='configured'

@pytest.mark.parametrize('messages',[[],None,'text',[{}],[{'role':'bad','content':'text'}],[{'role':'user','content':' '}],[{'role':'user','content':None}],['text']])
def test_invalid_messages(boundary,messages):
    with pytest.raises(ai.AIProviderError):ai.generate_chat(messages)
    boundary[1].assert_not_called()

@pytest.mark.parametrize('response',[None,{}, {'message':{}},{'message':{'content':''}},{'message':{'content':' '}},{'message':{'content':None}},{'message':{'content':42}}])
def test_bad_response(boundary,response):
    boundary[0].chat.return_value=response
    with pytest.raises(ai.AIResponseError):ai.generate_chat([{'role':'user','content':'Question'}])


def test_object_response(boundary):
    boundary[0].chat.return_value=SimpleNamespace(message=SimpleNamespace(content=' output \n'))
    assert ai.generate_chat([{'role':'assistant','content':'Previous answer'}])==' output \n'

@pytest.mark.parametrize('failure,expected',[(ConnectionError('offline'),ai.AIConnectionError),(httpx.ConnectError('offline'),ai.AIConnectionError),(httpx.ReadTimeout('timeout'),ai.AIConnectionError),(TimeoutError('timeout'),ai.AIConnectionError),(RuntimeError('provider'),ai.AIProviderError)])
def test_failures(boundary,failure,expected):
    boundary[0].chat.side_effect=failure
    with pytest.raises(expected) as error:ai.generate_chat([{'role':'user','content':'Question'}])
    assert error.value.__cause__ is failure
    assert boundary[0].chat.call_count==1

@pytest.mark.parametrize('model',['', ' ',42])
def test_bad_override(boundary,model):
    with pytest.raises(ai.AIProviderError):ai.generate_chat([{'role':'user','content':'Question'}],model=model)
    boundary[1].assert_not_called()


def test_production_boundary_guard():
    root=Path(__file__).resolve().parents[1]
    for path in root.glob('*.py'):
        tree=ast.parse(path.read_text())
        if path.name!='ai_provider.py':
            assert not any((isinstance(n,ast.Import) and any(a.name=='ollama' for a in n.names)) or (isinstance(n,ast.ImportFrom) and n.module=='ollama') for n in ast.walk(tree)),path.name
        if path.name!='ai_provider.py':assert 'ollama.chat(' not in path.read_text(),path.name
        if path.name!='config.py':
            assert 'llama3.2:3b' not in path.read_text(),path.name
            assert 'qwen2.5:3b' not in path.read_text(),path.name
    assert 'all-MiniLM-L6-v2' in (root/'config.py').read_text()
    assert 'get_embedding_model_name()' in (root/'vector_store.py').read_text()


def test_configured_host_forwarded(boundary, monkeypatch):
    monkeypatch.setenv('EDUAGENT_OLLAMA_BASE_URL', 'http://localhost:1234')
    ai.generate_chat([{'role':'user','content':'Question'}])
    boundary[1].assert_called_once_with(host='http://localhost:1234',timeout=120)


def test_client_creation_failure(boundary):
    failure = ConnectionError('offline')
    boundary[1].side_effect = failure
    with pytest.raises(ai.AIConnectionError) as error:
        ai.generate_chat([{'role':'user','content':'Question'}])
    assert error.value.__cause__ is failure
