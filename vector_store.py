from retrieval import build_filter
from config import get_embedding_model_name
import os
from pathlib import Path
from threading import RLock
from content_agent import extract_text_from_pdf
from chunking import chunk_text

# Empty caches only: import performs no Chroma/model initialization or writes.
_storage_lock = RLock()
_clients = {}
_collections = {}
_embedding_function = None


def get_storage_path(path=None):
    value = os.environ.get('EDUAGENT_CHROMA_PATH', './chroma_db') if path is None else path
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise ValueError('Chroma path must be a nonblank filesystem path.')
    return str(Path(value).expanduser().resolve())


def get_embedding_function():
    global _embedding_function
    with _storage_lock:
        if _embedding_function is None:
            from chromadb.utils import embedding_functions
            _embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=get_embedding_model_name())
        return _embedding_function


def get_chroma_client(path=None):
    resolved = get_storage_path(path)
    with _storage_lock:
        if resolved not in _clients:
            import chromadb
            _clients[resolved] = chromadb.PersistentClient(path=resolved)
        return _clients[resolved]


def get_collection(path=None, *, client=None, embedding_function=None):
    # Injected clients/functions bypass default caches; no production access.
    if client is not None:
        function = get_embedding_function() if embedding_function is None else embedding_function
        return client.get_or_create_collection(name='course_material', embedding_function=function)
    if embedding_function is not None:
        return get_chroma_client(path).get_or_create_collection(name='course_material', embedding_function=embedding_function)
    resolved = get_storage_path(path)
    with _storage_lock:
        if resolved not in _collections:
            # Load the model before opening persistent storage. Initialization
            # failures do not leave a newly opened database behind.
            function = get_embedding_function()
            _collections[resolved] = get_chroma_client(resolved).get_or_create_collection(
                name='course_material', embedding_function=function)
        return _collections[resolved]


def _resolve_collection(collection, path):
    return get_collection(path) if collection is None else collection


def add_pdf_to_database(pdf_path, source_name, course="General", unit="Unit 1", *, collection=None, path=None):
    """
    Reads a PDF, chunks it, and stores each chunk in ChromaDB —
    now tagged with which course and unit it belongs to.
    """
    text = extract_text_from_pdf(pdf_path)
    chunks = chunk_text(text)

    ids = [f"{source_name}_chunk_{i}" for i in range(len(chunks))]

    # Every chunk now remembers which file, course, and unit it came from
    metadatas = [
        {"source": source_name, "course": course, "unit": unit}
        for _ in chunks
    ]

    _resolve_collection(collection, path).add(
        documents=chunks,
        ids=ids,
        metadatas=metadatas
    )

    print(f"✅ Stored {len(chunks)} chunks from '{source_name}' ({course} / {unit}) in the database")


def search_database(query, n_results=3, course=None, *, semester=None, subject=None, unit=None, material_id=None, collection=None, path=None):
    """
    Given a question, finds the most relevant chunks — optionally
    restricted to a single course.
    """
    query_filter = build_filter(dict(course=course or None, semester=semester, subject=subject, unit=unit, material_id=material_id))

    results = _resolve_collection(collection, path).query(
        query_texts=[query],
        n_results=n_results,
        where=query_filter
    )
    return results

if __name__ == "__main__":
    # Add your sample PDF to the database
    add_pdf_to_database("sample_lecture.pdf", "sample_lecture")

    # Test a search
    test_query = "Covariance matrix"  # change this to something
                                                    # relevant to your actual PDF
    results = search_database(test_query)

    print("\n🔍 Search results for:", test_query)
    for i, doc in enumerate(results["documents"][0]):
        print(f"\n--- Result {i+1} ---")
        print(doc[:300])  # print first 300 characters of each match

def get_all_chunks(source_name=None, course=None, limit=15, *, collection=None, path=None):
    """
    Grabs a batch of stored chunks for quiz generation.
    Can filter by source file and/or course.
    """
    where_clause = build_filter(dict(source=source_name or None, course=course or None))
    collection = _resolve_collection(collection, path)
    results = collection.get(where=where_clause, limit=limit) if where_clause else collection.get(limit=limit)

    # Return both the text AND the metadata, so questions can cite their source
    return results["documents"], results["metadatas"]

# Exact-ID APIs for managed material lifecycle; no source-based deletion.
def add_material_chunks(ids, chunks, metadata, *, collection=None, path=None):
    _resolve_collection(collection, path).add(ids=ids, documents=chunks, metadatas=[dict(metadata) for _ in chunks])


def get_material_chunks(ids, *, collection=None, path=None):
    return _resolve_collection(collection, path).get(ids=ids)


def delete_material_chunks(ids, *, collection=None, path=None):
    if ids:
        _resolve_collection(collection, path).delete(ids=ids)


def update_material_chunks(ids, metadatas, *, collection=None, path=None):
    if ids:
        _resolve_collection(collection, path).update(ids=ids, metadatas=metadatas)
