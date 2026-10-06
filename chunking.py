def chunk_text(text, chunk_size=500, overlap=50):
    """
    Splits a long text into smaller overlapping chunks.

    chunk_size = how many characters per chunk
    overlap = how many characters repeat between chunks, so we don't
              accidentally cut a sentence in half and lose meaning
    """
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    if not isinstance(overlap, int) or isinstance(overlap, bool) or overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk.strip())
        start += chunk_size - overlap  # move forward, but overlap a bit

    # Remove any empty chunks (can happen at the very end)
    chunks = [c for c in chunks if c]
    return chunks


# Quick test
if __name__ == "__main__":
    sample = "This is sentence one. " * 100  # fake long text for testing
    result = chunk_text(sample)
    print(f"Created {len(result)} chunks")
    print("First chunk:\n", result[0])