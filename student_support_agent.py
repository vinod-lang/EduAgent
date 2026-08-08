import ollama
from vector_store import search_database

# Change this to whichever model you pulled
MODEL_NAME = "llama3.2:3b"   # or "llama3.1:8b" if you have more RAM


def answer_question(question, n_chunks=3):
    """
    The full RAG pipeline:
    1. Search the vector database for relevant chunks
    2. Stuff those chunks into a prompt as "context"
    3. Ask the local model to answer USING ONLY that context
    """

    # Step 1: Retrieval
    results = search_database(question, n_results=n_chunks)
    retrieved_chunks = results["documents"][0]

    if not retrieved_chunks:
        return "I couldn't find anything relevant in the course material."

    context = "\n\n".join(retrieved_chunks)

    # Step 2: Build the prompt (same grounding idea as before)
    system_prompt = """You are a helpful teaching assistant. Answer the
student's question using ONLY the course material provided below.
If the answer is not contained in the material, say
"I don't have that information in the course material" —
do not make up an answer."""

    user_prompt = f"""Course material:
{context}

Student's question: {question}"""

    # Step 3: Generation — call the LOCAL model instead of an API
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    return response["message"]["content"]


if __name__ == "__main__":
    print("💬 Student Support Agent (type 'quit' to exit)\n")

    while True:
        question = input("Ask a question: ")
        if question.lower() == "quit":
            break

        answer = answer_question(question)
        print(f"\n🤖 {answer}\n")