"""The sole generative Ollama boundary. No retries or embedding operations."""
from collections.abc import Mapping, Sequence
import httpx
import ollama
import math
import time
from dataclasses import dataclass
from contextvars import ContextVar
from config import get_ai_profile, AIStackStatus
from config import get_ai_config, ConfigurationError

class AIProviderError(RuntimeError):
    pass

class AIConnectionError(AIProviderError):
    pass

class AIResponseError(AIProviderError):
    pass


def configured():
    try:
        return get_ai_config()
    except ConfigurationError as exc:
        raise AIProviderError(f'Invalid AI configuration: {exc}') from exc


def get_default_model_name() -> str:
    return configured().model


def _chat(messages, model=None, *, options=None, timeout_seconds=None, think=None, response_format=None):
    clear_generation_selection()
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)) or not messages:
        raise AIProviderError('Messages must be a nonempty sequence.')
    normalized = []
    for message in messages:
        if not isinstance(message, Mapping) or message.get('role') not in ('system','user','assistant') or not isinstance(message.get('content'), str) or not message['content'].strip():
            raise AIProviderError('Each message requires a system/user/assistant role and nonblank text content.')
        normalized.append(dict(message))
    settings = configured()
    selected = settings.model if model is None else model
    if not isinstance(selected, str) or not selected.strip():
        raise AIProviderError('Model override must be nonblank text.')
    if timeout_seconds is not None and (isinstance(timeout_seconds,bool) or not isinstance(timeout_seconds,(int,float)) or not math.isfinite(timeout_seconds) or timeout_seconds<=0):
        raise AIProviderError('Timeout override must be finite and positive.')
    if options is not None:
        if not isinstance(options,Mapping) or set(options)-{'temperature','seed','num_ctx','num_predict'}:
            raise AIProviderError('Unsupported generation options.')
        for key,value in options.items():
            if key=='temperature':
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=2:raise AIProviderError('Invalid temperature.')
            elif type(value)is not int or not 0<=value<=100000 or (key!='seed' and value==0):raise AIProviderError('Invalid integer generation option.')
    if think is not None and type(think)is not bool:raise AIProviderError('Thinking override must be boolean.')
    kwargs={}
    if options is not None:kwargs['options']=dict(options)
    if think is not None:kwargs['think']=think
    if response_format is not None:
        if not isinstance(response_format,Mapping) or response_format.get("type")!="object":
            raise AIProviderError("Structured response schema must describe an object.")
        import json
        try: kwargs["format"]=json.loads(json.dumps(dict(response_format),allow_nan=False))
        except (ValueError,TypeError) as exc: raise AIProviderError("Invalid structured response schema.") from exc
    started=time.perf_counter()
    try:
        with ollama.Client(host=settings.base_url, timeout=settings.timeout_seconds if timeout_seconds is None else timeout_seconds) as client:
            selection=resolve_model(client,settings,model)
            response = client.chat(model=selection.effective_model, messages=normalized, **kwargs)
    except AIProviderError:
        raise
    except (httpx.TransportError, ConnectionError, TimeoutError, OSError) as exc:
        raise AIConnectionError('Local AI service is unavailable or timed out. Make sure Ollama is running.') from exc
    except Exception as exc:
        raise AIProviderError('Ollama generation failed. Check that the configured model is installed.') from exc
    try:
        message = response.get('message') if isinstance(response, Mapping) else response.message
        content = message.get('content') if isinstance(message, Mapping) else message.content
    except (AttributeError, TypeError, KeyError) as exc:
        raise AIResponseError('AI service returned an unusable response.') from exc
    if not isinstance(content, str) or not content.strip():
        raise AIResponseError('AI service returned missing or empty text.')
    elapsed=time.perf_counter()-started
    def metric(name):
        value=response.get(name) if isinstance(response,Mapping) else getattr(response,name,None)
        return value if type(value)is int and value>=0 else None
    _last_selection.set(selection)
    return ChatMeasurement(content,elapsed,metric('eval_count'),metric('prompt_eval_count'),metric('total_duration'),metric('load_duration'),metric('eval_duration'),selection.effective_model,settings.provider,selection.fallback_active)


@dataclass(frozen=True)
class ChatMeasurement:
    text: str
    elapsed_seconds: float
    output_tokens: int | None
    prompt_tokens: int | None
    total_duration_ns: int | None
    load_duration_ns: int | None
    eval_duration_ns: int | None
    effective_model: str | None = None
    provider: str | None = None
    fallback_active: bool = False


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_structured_output: bool


def get_provider_capabilities():
    return ProviderCapabilities(supports_structured_output=configured().provider == 'ollama')


def generate_chat(messages, model=None, *, response_format=None) -> str:
    if response_format is None:
        return _chat(messages,model).text
    return _chat(messages,model,response_format=response_format).text


def generate_chat_measured(messages, model=None, *, options=None, timeout_seconds=None, think=None, response_format=None):
    """Explicit opt-in instrumentation; never changes application defaults."""
    return _chat(messages,model,options=options,timeout_seconds=timeout_seconds,think=think,response_format=response_format)


@dataclass(frozen=True)
class ModelSelection:
    preferred_model: str
    effective_model: str
    fallback_active: bool

_last_selection=ContextVar('eduagent_last_selection',default=None)


def clear_generation_selection():
    _last_selection.set(None)


def get_last_generation_selection():
    return _last_selection.get()


def available_models(client):
    """Read Ollama's local inventory only. Never downloads or invokes a shell."""
    response=client.list()
    entries=response.get('models') if isinstance(response,Mapping) else getattr(response,'models',None)
    if not isinstance(entries,Sequence) or isinstance(entries,(str,bytes)):
        raise AIResponseError('Local model inventory could not be read. Check Ollama availability.')
    names=set()
    for entry in entries:
        name=entry.get('model',entry.get('name')) if isinstance(entry,Mapping) else getattr(entry,'model',None)
        if not isinstance(name,str) or not name.strip():raise AIResponseError('Local model inventory was unusable. Check Ollama availability.')
        names.add(name.strip())
    return names


def resolve_model(client,settings,override=None):
    # Explicit benchmark overrides must never silently select another model.
    if override is not None:return ModelSelection(override.strip(),override.strip(),False)
    names=available_models(client)
    def present(name):
        return name in names or (':' not in name.rsplit('/',1)[-1] and name+':latest' in names)
    if present(settings.model):return ModelSelection(settings.model,settings.model,False)
    if settings.fallback_model and present(settings.fallback_model):
        return ModelSelection(settings.model,settings.fallback_model,settings.fallback_model!=settings.model)
    raise AIProviderError('Neither the preferred model nor the configured fallback is installed locally. Install a reviewed model manually or adjust the local AI configuration; EduAgent will not download models.')


def get_ai_stack_status():
    """Explicit health read; no inference, downloads, paths or production storage."""
    try:
        profile=get_ai_profile();settings=configured()
        with ollama.Client(host=settings.base_url,timeout=settings.timeout_seconds) as client:
            selection=resolve_model(client,settings)
    except AIProviderError:raise
    except ConfigurationError as exc:raise AIProviderError('Invalid AI stack configuration.') from exc
    except (httpx.TransportError,ConnectionError,TimeoutError,OSError) as exc:
        raise AIConnectionError('Local AI service is unavailable. Check Ollama availability.') from exc
    except Exception as exc:raise AIProviderError('Local AI stack status could not be read.') from exc
    return AIStackStatus(profile.provider,profile.preferred_model,selection.effective_model,selection.fallback_active,profile.embedding_model,profile.candidate_k,profile.final_k,profile.distance_threshold,profile.reranker_enabled,profile.router_enabled)
