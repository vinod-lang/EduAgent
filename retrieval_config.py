"""Independent RAG settings for the verified cosine-distance collection."""
from dataclasses import dataclass
import math
from config import ConfigurationError, DEFAULT_CANDIDATE_K, DEFAULT_FINAL_K, DEFAULT_DISTANCE_THRESHOLD, retrieval_environment

@dataclass(frozen=True)
class RetrievalConfig:
    candidate_k: int = DEFAULT_CANDIDATE_K
    final_k: int = DEFAULT_FINAL_K
    max_distance: float = DEFAULT_DISTANCE_THRESHOLD

    def __post_init__(self):
        for name in ('candidate_k', 'final_k'):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 200:
                raise ConfigurationError(f'{name} must be an integer between 1 and 200.')
        if self.candidate_k < self.final_k:
            raise ConfigurationError('candidate_k must be at least final_k.')
        if isinstance(self.max_distance, bool) or not isinstance(self.max_distance, (int, float)) or not math.isfinite(self.max_distance) or not 0 <= self.max_distance <= 2:
            raise ConfigurationError('max_distance must be a finite cosine distance between 0 and 2.')


def get_retrieval_config(*, candidate_k=None, final_k=None, max_distance=None):
    """Explicit overrides > environment > defaults. Invalid settings fail closed."""
    try:
        return RetrievalConfig(*retrieval_environment(candidate_k=candidate_k,final_k=final_k,max_distance=max_distance))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ConfigurationError(f'Invalid retrieval configuration: {exc}') from exc
