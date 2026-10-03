"""Independent RAG settings for the verified cosine-distance collection."""
from dataclasses import dataclass
import math
import os
from config import ConfigurationError

@dataclass(frozen=True)
class RetrievalConfig:
    candidate_k: int = 15
    final_k: int = 5
    max_distance: float = 0.65

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
        return RetrievalConfig(
            int(os.environ.get('EDUAGENT_RAG_CANDIDATE_K', '15')) if candidate_k is None else candidate_k,
            int(os.environ.get('EDUAGENT_RAG_FINAL_K', '5')) if final_k is None else final_k,
            float(os.environ.get('EDUAGENT_RAG_MAX_DISTANCE', '0.65')) if max_distance is None else max_distance)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ConfigurationError(f'Invalid retrieval configuration: {exc}') from exc
