import ollama
from vector_store import search_database

# Change this to whichever model you pulled
MODEL_NAME = "llama3.2:3b"   # or "llama3.1:8b" if you have more RAM


def answer_question(question, n_chunks=3, course=None):
    """
    RAG pipeline, now with:
    1. Optional course scoping
    2. Source citation shown alongside the answer
    """
    results = search_database(question, n_results=n_chunks, course=course)
    retrieved_chunks = results["documents"][0]
    retrieved_metadata = results["metadatas"][0]

    if not retrieved_chunks:
        return "I couldn't find anything relevant in the course material.", []

    context = "\n\n".join(retrieved_chunks)

    system_prompt = """You are a helpful teaching assistant. Answer the
student's question using ONLY the course material provided below.
If the answer is not contained in the material, say
"I don't have that information in the course material" —
do not make up an answer."""

    user_prompt = f"""Course material:
{context}

Student's question: {question}"""

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    answer = response["message"]["content"]

    # Build a simple list of unique sources used, for citation display
    sources = list({f"{m['source']} ({m['unit']})" for m in retrieved_metadata})

    return answer, sources

if __name__ == "__main__":
    print("💬 Student Support Agent (type 'quit' to exit)\n")

    while True:
        question = input("Ask a question: ")
        if question.lower() == "quit":
            break

        answer, sources = answer_question(question)
        print(f"\n🤖 {answer}")
        print(f"📚 Sources: {', '.join(sources)}\n")