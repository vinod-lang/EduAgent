import ollama
import json
from vector_store import get_all_chunks

MODEL_NAME = "llama3.2:3b"


def generate_questions(
    source_name=None,
    course=None,
    num_questions=5,
    question_type="MCQ",
    difficulty="Medium"
):
    """
    Generates questions with configurable type and difficulty,
    with each question tagged to which chunk it came from.
    """
    chunks, metadatas = get_all_chunks(source_name=source_name, course=course)

    if not chunks:
        return None

    # Number the chunks so the model can reference which one it used
    numbered_content = "\n\n".join(
        f"[Chunk {i}] {chunk}" for i, chunk in enumerate(chunks)
    )

    if question_type == "MCQ":
        format_instruction = """Each item must have exactly 4 options
labeled A-D with only one correct answer. Use this structure:
[
  {
    "question": "...",
    "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
    "correct_answer": "A",
    "explanation": "...",
    "source_chunk": 0
  }
]"""
    else:  # Descriptive / short-answer
        format_instruction = """Each item is a short-answer or descriptive
question with a model answer. Use this structure:
[
  {
    "question": "...",
    "model_answer": "...",
    "source_chunk": 0
  }
]"""

    system_prompt = f"""You are an exam question generator for a professor.
Respond with ONLY valid JSON, no extra text, no markdown fences.
Every question must include "source_chunk": the number of the chunk
(shown as [Chunk N] in the material) that the question was based on.
{format_instruction}"""

    user_prompt = f"""Generate {num_questions} {difficulty}-difficulty
{question_type} questions based on the numbered course material below.
Test real understanding, not memorized wording.

Course material:
{numbered_content}
"""

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    raw_text = response["message"]["content"]
    cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        questions = json.loads(cleaned)
    except json.JSONDecodeError:
        print("⚠️ Could not parse JSON. Raw model output was:\n")
        print(raw_text)
        return None

    # Attach the actual source metadata (filename/unit) using source_chunk index
    for q in questions:
        chunk_index = q.get("source_chunk")
        if chunk_index is not None and 0 <= chunk_index < len(metadatas):
            meta = metadatas[chunk_index]
            q["source_label"] = f"{meta['source']} ({meta['unit']})"
        else:
            q["source_label"] = "Unknown"

    return questions


if __name__ == "__main__":
    questions = generate_questions(
        source_name="PCA",
        num_questions=3,
        question_type="MCQ",
        difficulty="Medium"
    )

    if questions:
        for i, q in enumerate(questions, start=1):
            print(f"\nQ{i}. {q['question']}")
            if "options" in q:
                for letter, opt in q["options"].items():
                    print(f"   {letter}) {opt}")
                print(f"   Answer: {q['correct_answer']}")
            else:
                print(f"   Model answer: {q['model_answer']}")
            print(f"   📚 Source: {q['source_label']}")