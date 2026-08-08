import ollama

MODEL_NAME = "llama3.2:3b"


def classify_intent(user_input):
    """
    Reads a plain-English request and decides which agent(s) should
    handle it. Now supports a combined "quiz_and_notice" case for
    genuine multi-agent chaining.
    """

    system_prompt = """You are a routing assistant for an educational AI
system. Given a user's request, classify it into EXACTLY ONE of these
categories:

- question -> the user is asking a question about course content
- quiz -> the user wants ONLY questions/an MCQ set/a quiz generated
- document -> the user wants ONLY a notice, circular, or email drafted
- quiz_and_notice -> the user wants BOTH a quiz/test generated AND a
  notice/announcement about it, in the same request
- unknown -> anything that doesn't clearly fit the above

Respond with ONLY the single category phrase in lowercase. No
punctuation, no explanation, nothing else."""

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]
    )

    intent = response["message"]["content"].strip().lower()

    valid_intents = ["question", "quiz", "document", "quiz_and_notice"]
    if intent not in valid_intents:
        intent = "unknown"

    return intent