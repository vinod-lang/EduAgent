import ollama

MODEL_NAME = "llama3.2:3b"


def classify_intent(user_input):
    """
    Reads a plain-English request and decides which agent should handle it.
    Returns one of: "question", "quiz", "document", "unknown"
    """

    system_prompt = """You are a routing assistant for an educational AI
system. Given a user's request, classify it into EXACTLY ONE of these
categories:

- question -> the user is asking a question about course content
- quiz -> the user wants questions, an MCQ set, or a quiz generated
- document -> the user wants a notice, circular, or email drafted
- unknown -> anything that doesn't clearly fit the above

Respond with ONLY the single category word in lowercase. No punctuation,
no explanation, nothing else."""

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]
    )

    intent = response["message"]["content"].strip().lower()

    # Safety net: if the model outputs something unexpected
    # (extra words, punctuation), fall back to "unknown" instead of crashing
    valid_intents = ["question", "quiz", "document"]
    if intent not in valid_intents:
        intent = "unknown"

    return intent
