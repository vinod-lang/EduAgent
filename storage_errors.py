"""Import-safe local storage failures shared by lifecycle and vector adapters."""

class EmbeddingUnavailableError(RuntimeError):
    """Local embedding resources failed to initialize; preserve private cause."""
