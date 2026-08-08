import ollama

MODEL_NAME = "llama3.2:3b"


def generate_document(instruction, doc_type="Notice"):
    """
    Drafts a circular, notice, or email based on a short instruction
    from the user, in a professional institutional format.
    """

    system_prompt = f"""You are an assistant that drafts official {doc_type}s
for a college/university. Write in a formal, professional tone suitable
for students and faculty. Include a clear title, date placeholder,
body content, and a closing line with a designation placeholder
(e.g. "Head of Department"). Do not add any commentary before or
after the document itself — output ONLY the document text."""

    user_prompt = f"""Draft a {doc_type} based on this instruction:
{instruction}"""

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    return response["message"]["content"]


if __name__ == "__main__":
    doc = generate_document(
        instruction="Classes will remain suspended on 15th August due to Independence Day celebrations.",
        doc_type="Notice"
    )
    print(doc)