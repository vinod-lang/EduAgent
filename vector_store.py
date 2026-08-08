import chromadb
from chromadb.utils import embedding_functions
from content_agent import extract_text_from_pdf
from chunking import chunk_text

# 1. Set up the embedding function (this downloads a small free AI model
#    the first time you run it, then reuses it)
embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

# 2. Create a persistent ChromaDB client
#    "persistent" means it saves to disk, so your data survives after
#    you close the program
client = chromadb.PersistentClient(path="./chroma_db")

# 3. Create (or get) a "collection" — think of this like a table in a database
collection = client.get_or_create_collection(
    name="course_material",
    embedding_function=embedding_fn
)


def add_pdf_to_database(pdf_path, source_name, course="General", unit="Unit 1"):
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

    collection.add(
        documents=chunks,
        ids=ids,
        metadatas=metadatas
    )

    print(f"✅ Stored {len(chunks)} chunks from '{source_name}' ({course} / {unit}) in the database")


def search_database(query, n_results=3, course=None):
    """
    Given a question, finds the most relevant chunks — optionally
    restricted to a single course.
    """
    query_filter = {"course": course} if course else None

    results = collection.query(
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

def get_all_chunks(source_name=None, limit=15):
    """
    Grabs a batch of stored chunks to use as material for generating
    questions. If source_name is given, only pulls chunks from that file.
    """
    if source_name:
        results = collection.get(
            where={"source": source_name},
            limit=limit
        )
    else:
        results = collection.get(limit=limit)

    return results["documents"]