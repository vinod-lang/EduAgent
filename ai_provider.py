"""The sole generative Ollama boundary. No retries or embedding operations."""
from collections.abc import Mapping, Sequence
import httpx
import ollama
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


def generate_chat(messages, model=None) -> str:
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
    try:
        with ollama.Client(host=settings.base_url, timeout=settings.timeout_seconds) as client:
            response = client.chat(model=selected.strip(), messages=normalized)
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
    return content  # retain original text/whitespace for agent behavior compatibility
