"""Synthetic offline reliability contracts; no model or production storage."""
import json
from unittest.mock import Mock
import httpx
import pytest
import ai_provider
from structured_generation import *

SCHEMA={'type':'object','properties':{'value':{'type':'string'}},'required':['value'],'additionalProperties':False}
MESSAGES=[{'role':'user','content':'Synthetic request'}]

@pytest.fixture
def chat(monkeypatch):
    mock=Mock(return_value='{"value":"ok"}')
    monkeypatch.setattr(ai_provider,'generate_chat',mock)
    return mock

@pytest.mark.parametrize('raw',['{"value":"ok"}','```json\n{"value":"ok"}\n```','Here is the result:\n{"value":"ok"}'])
def test_supported_wrappers(chat,raw):
    chat.return_value=raw
    result=generate_structured(MESSAGES,SCHEMA,lambda raw:json.loads(raw)['value'])
    assert result.accepted and result.value=='ok' and result.attempt_count==1
    assert chat.call_args.kwargs['response_format']==SCHEMA
    assert 'Synthetic request' not in repr(result)

@pytest.mark.parametrize('raw',['{} {}','{"value":"x"} print(1)','print(1) {"value":"x"}','[]','null','bad','{"value":"x",}','{"value":"x","value":"y"}','{"value":NaN}','```python\n{}\n```','```json\n{}\n```\nOther answer','Here is another result: {}'])
def test_unsafe_extraction(chat,raw):
    chat.return_value=raw
    result=generate_structured(MESSAGES,SCHEMA,json.loads)
    assert result.failure==Failure.INVALID_JSON and result.attempt_count==1

@pytest.mark.parametrize('raw',['{}','{"value":3}','{"value":"x","extra":true}'])
def test_schema_failures(chat,raw):
    chat.return_value=raw
    assert generate_structured(MESSAGES,SCHEMA,json.loads).failure==Failure.SCHEMA_INVALID

@pytest.mark.parametrize('first',['bad','{}'])
def test_one_successful_retry(chat,first):
    chat.side_effect=[first,'{"value":"ok"}']
    result=generate_structured(MESSAGES,SCHEMA,json.loads,retry=True)
    assert result.accepted and result.attempt_count==2 and result.first_failure
    assert first not in chat.call_args.kwargs['messages'][-1]['content']
    assert len(chat.call_args.kwargs['messages'])==2

def test_failed_retry_cap(chat):
    chat.side_effect=['bad','bad','{"value":"ok"}']
    result=generate_structured(MESSAGES,SCHEMA,json.loads,retry=True)
    assert result.failure==Failure.INVALID_JSON and chat.call_count==2

@pytest.mark.parametrize('error',[ValueError('PRIVATE'),FactPreservationFailure('PRIVATE')])
def test_product_errors_never_retry(chat,error):
    def validate(_):raise error
    result=generate_structured(MESSAGES,SCHEMA,validate,retry=True)
    assert result.attempt_count==1 and 'PRIVATE' not in repr(result)
    with pytest.raises(ValueError,match='No result was saved'):result.require(ValueError,'synthetic result')

@pytest.mark.parametrize('timeout',[False,True])
def test_provider_failures(chat,timeout):
    error=ai_provider.AIConnectionError('PRIVATE')
    if timeout:error.__cause__=httpx.ReadTimeout('PRIVATE')
    chat.side_effect=error
    result=generate_structured(MESSAGES,SCHEMA,json.loads,retry=True)
    assert result.failure==(Failure.TIMEOUT if timeout else Failure.PROVIDER_ERROR)
    assert result.attempt_count==1
    with pytest.raises(ai_provider.AIConnectionError):result.require(ValueError,'result')

@pytest.mark.parametrize('retry',[1,2,None,'yes'])
def test_invalid_retry_policy(chat,retry):
    with pytest.raises(ValueError):generate_structured(MESSAGES,SCHEMA,json.loads,retry=retry)
    chat.assert_not_called()

def test_capability_without_native_schema(chat,monkeypatch):
    monkeypatch.setattr(ai_provider,'get_provider_capabilities',lambda:ai_provider.ProviderCapabilities(False))
    assert generate_structured(MESSAGES,SCHEMA,json.loads).accepted
    assert 'response_format' not in chat.call_args.kwargs

def test_oversized_response(chat):
    chat.return_value='x'*101
    assert generate_structured(MESSAGES,SCHEMA,json.loads,maximum=100).failure==Failure.INVALID_JSON
