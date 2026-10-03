"""Generative configuration: EduAgent env > OLLAMA_HOST fallback > defaults.

Read per request; no .env loading, embedding settings, or credentials.
"""
from dataclasses import dataclass
import math
import os
from urllib.parse import urlsplit

DEFAULT_MODEL = 'llama3.2:3b'

class ConfigurationError(ValueError):
    pass

@dataclass(frozen=True)
class AIConfig:
    provider: str
    model: str
    base_url: str
    timeout_seconds: float


def get_ai_config():
    provider = os.environ.get('EDUAGENT_LLM_PROVIDER', 'ollama').strip().lower()
    model = os.environ.get('EDUAGENT_LLM_MODEL', DEFAULT_MODEL).strip()
    url = os.environ.get('EDUAGENT_OLLAMA_BASE_URL', os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')).strip()
    if provider != 'ollama':
        raise ConfigurationError('EDUAGENT_LLM_PROVIDER supports only ollama.')
    if not model:
        raise ConfigurationError('EDUAGENT_LLM_MODEL must not be blank.')
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        parsed.port
    except ValueError as exc:
        raise ConfigurationError('Ollama base URL must be an HTTP(S) URL without credentials.') from exc
    try:
        timeout = float(os.environ.get('EDUAGENT_LLM_TIMEOUT_SECONDS', '120'))
    except ValueError as exc:
        raise ConfigurationError('EDUAGENT_LLM_TIMEOUT_SECONDS must be numeric.') from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ConfigurationError('EDUAGENT_LLM_TIMEOUT_SECONDS must be finite and positive.')
    return AIConfig(provider, model, url, timeout)
