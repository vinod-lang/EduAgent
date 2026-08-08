import ollama
import json
from vector_store import get_all_chunks

MODEL_NAME = "llama3.2:3b"   # match whatever model you're using


def generate_mcqs(source_name=None, num_questions=5):
    """
    Generates multiple-choice questions with an answer key,
    based on the stored course material.
    """
    chunks = get_all_chunks(source_name=source_name)
    content = "\n\n".join(chunks)

    system_prompt = """You are an exam question generator for a professor.
You must respond with ONLY valid JSON, no extra text, no markdown code
fences, no explanation before or after. Follow this exact structure:

[
  {
    "question": "question text here",
    "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
    "correct_answer": "A",
    "explanation": "one sentence on why this is correct"
  }
]
"""

    user_prompt = f"""Based on the following course material, generate
{num_questions} multiple-choice questions that test real understanding
of the concepts (not just memorized wording). Each question must have
exactly 4 options with only one correct answer.

Course material:
{content}
"""

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    raw_text = response["message"]["content"]

    # Models sometimes wrap JSON in ```json ... ``` even when told not to.
    # This cleans that up before parsing.
    cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        questions = json.loads(cleaned)
        return questions
    except json.JSONDecodeError:
        print("⚠️ Could not parse JSON. Raw model output was:\n")
        print(raw_text)
        return None


def print_quiz(questions):
    """Nicely prints the generated quiz and a separate answer key."""
    if not questions:
        return

    print("\n" + "=" * 50)
    print("QUIZ")
    print("=" * 50)
    for i, q in enumerate(questions, start=1):
        print(f"\nQ{i}. {q['question']}")
        for letter, option_text in q["options"].items():
            print(f"   {letter}) {option_text}")

    print("\n" + "=" * 50)
    print("ANSWER KEY")
    print("=" * 50)
    for i, q in enumerate(questions, start=1):
        print(f"Q{i}: {q['correct_answer']} — {q['explanation']}")


if __name__ == "__main__":
    print("Generating quiz... (this can take 20-40 seconds on a local model)\n")
    quiz = generate_mcqs(source_name="sample_lecture", num_questions=5)
    print_quiz(quiz)