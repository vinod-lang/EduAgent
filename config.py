"""Generative configuration: EduAgent env > OLLAMA_HOST fallback > defaults.

Read per request; no .env loading, embedding settings, or credentials.
"""
from dataclasses import dataclass
import math
import os
from urllib.parse import urlsplit

DEFAULT_MODEL = 'qwen2.5:3b'
DEFAULT_FALLBACK_MODEL = 'llama3.2:3b'
DEFAULT_EMBEDDING_MODEL = 'all-MiniLM-L6-v2'
DEFAULT_CANDIDATE_K = 15
DEFAULT_FINAL_K = 5
# October 2026 Linux synthetic evaluation; real NIT corpus recalibration required.
DEFAULT_DISTANCE_THRESHOLD = 0.50

class ConfigurationError(ValueError):
    pass

@dataclass(frozen=True)
class AIConfig:
    provider: str
    model: str
    base_url: str
    timeout_seconds: float
    fallback_model: str | None = DEFAULT_FALLBACK_MODEL


def get_ai_config():
    provider = os.environ.get('EDUAGENT_LLM_PROVIDER', 'ollama').strip().lower()
    model = os.environ.get('EDUAGENT_LLM_PREFERRED_MODEL', os.environ.get('EDUAGENT_LLM_MODEL', DEFAULT_MODEL)).strip()
    fallback = os.environ.get('EDUAGENT_LLM_FALLBACK_MODEL', DEFAULT_FALLBACK_MODEL).strip()
    if not fallback:raise ConfigurationError('Fallback model must be nonblank, or none to disable it.')
    fallback = None if fallback.casefold()=='none' else fallback
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
    return AIConfig(provider, model, url, timeout, fallback)


DEFAULT_MAX_UPLOAD_MB = 20


def get_max_upload_bytes():
    """Independent ingestion limit, read per upload; no LLM configuration needed."""
    try:
        mb = float(os.environ.get('EDUAGENT_MAX_UPLOAD_MB', str(DEFAULT_MAX_UPLOAD_MB)))
    except ValueError as exc:
        raise ConfigurationError('EDUAGENT_MAX_UPLOAD_MB must be numeric.') from exc
    if not math.isfinite(mb) or not math.isfinite(mb * 1024 * 1024) or mb <= 0 or mb * 1024 * 1024 < 1:
        raise ConfigurationError('EDUAGENT_MAX_UPLOAD_MB must be finite and positive (at least one byte).')
    return int(mb * 1024 * 1024)


@dataclass(frozen=True)
class AIProfile:
    provider: str
    preferred_model: str
    fallback_model: str | None
    embedding_model: str
    candidate_k: int
    final_k: int
    distance_threshold: float
    reranker_enabled: bool = False
    router_enabled: bool = False


def get_embedding_model_name():
    value=os.environ.get('EDUAGENT_EMBEDDING_MODEL',DEFAULT_EMBEDDING_MODEL).strip()
    if value!=DEFAULT_EMBEDDING_MODEL:
        raise ConfigurationError('Embedding changes require a separately reviewed storage migration; keep the existing embedding model.')
    return value


def retrieval_environment(*,candidate_k=None,final_k=None,max_distance=None):
    """Central explicit > new-name environment > legacy-name > defaults."""
    defaults=(DEFAULT_CANDIDATE_K,DEFAULT_FINAL_K,DEFAULT_DISTANCE_THRESHOLD)
    values=[]
    try:
        for index,(override,key) in enumerate(zip((candidate_k,final_k,max_distance),('EDUAGENT_RAG_CANDIDATE_K','EDUAGENT_RAG_FINAL_K','EDUAGENT_RAG_DISTANCE_THRESHOLD'))):
            if override is not None:values.append(override);continue
            text=os.environ.get(key,os.environ.get('EDUAGENT_RAG_MAX_DISTANCE',str(defaults[index])) if index==2 else str(defaults[index]))
            values.append(float(text) if index==2 else int(text))
        return tuple(values)
    except (ValueError,TypeError,OverflowError) as exc:
        raise ConfigurationError('Invalid retrieval environment. Use numeric K values and a finite cosine threshold.') from exc


def get_ai_profile():
    ai=get_ai_config()
    from retrieval_config import get_retrieval_config
    rag=get_retrieval_config()
    # These components were not approved by evaluation. Reject attempts to enable.
    for key in ('EDUAGENT_RERANKER_ENABLED','EDUAGENT_ROUTER_ENABLED'):
        if os.environ.get(key,'false').strip().casefold() not in ('false','0'):
            raise ConfigurationError('Reranking and task-specific routing are not supported in this production profile.')
    return AIProfile(ai.provider,ai.model,ai.fallback_model,get_embedding_model_name(),rag.candidate_k,rag.final_k,rag.max_distance)


@dataclass(frozen=True)
class AIStackStatus:
    provider: str
    preferred_model: str
    effective_model: str
    fallback_active: bool
    embedding_model: str
    candidate_k: int
    final_k: int
    distance_threshold: float
    reranker_enabled: bool
    router_enabled: bool
