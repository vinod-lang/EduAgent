"""The sole generative Ollama boundary. No retries or embedding operations."""
from collections.abc import Mapping, Sequence
import httpx
import ollama
import math
import time
from dataclasses import dataclass
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


def _chat(messages, model=None, *, options=None, timeout_seconds=None, think=None):
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
    started=time.perf_counter()
    try:
        with ollama.Client(host=settings.base_url, timeout=settings.timeout_seconds if timeout_seconds is None else timeout_seconds) as client:
            response = client.chat(model=selected.strip(), messages=normalized, **kwargs)
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
    return ChatMeasurement(content,elapsed,metric('eval_count'),metric('prompt_eval_count'),metric('total_duration'),metric('load_duration'),metric('eval_duration'))


@dataclass(frozen=True)
class ChatMeasurement:
    text: str
    elapsed_seconds: float
    output_tokens: int | None
    prompt_tokens: int | None
    total_duration_ns: int | None
    load_duration_ns: int | None
    eval_duration_ns: int | None


def generate_chat(messages, model=None) -> str:
    return _chat(messages,model).text  # existing defaults/call shape preserved


def generate_chat_measured(messages, model=None, *, options=None, timeout_seconds=None, think=None):
    """Explicit opt-in instrumentation; never changes application defaults."""
    return _chat(messages,model,options=options,timeout_seconds=timeout_seconds,think=think)
