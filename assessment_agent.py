import ollama
import json
from vector_store import get_all_chunks

MODEL_NAME = "llama3.2:3b"


def generate_questions(
    source_name=None,
    course=None,
    num_questions=5,
    question_type="MCQ",
    difficulty="Medium",
    bloom_level="Understand"
):
    """
    Generates questions with configurable type, difficulty, and
    Bloom's Taxonomy cognitive level.
    """
    chunks, metadatas = get_all_chunks(source_name=source_name, course=course)

    if not chunks:
        return None

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
    "source_chunk": 0,
    "bloom_level": "Understand"
  }
]"""
    else:
        format_instruction = """Each item is a short-answer or descriptive
question with a model answer. Use this structure:
[
  {
    "question": "...",
    "model_answer": "...",
    "source_chunk": 0,
    "bloom_level": "Understand"
  }
]"""

    bloom_guidance = {
        "Remember": "Test recall of facts, definitions, and terminology.",
        "Understand": "Test explanation of concepts in the student's own words.",
        "Apply": "Test applying a concept to solve a new problem or scenario.",
        "Analyze": "Test breaking down a concept into its components or comparing ideas."
    }

    system_prompt = f"""You are an exam question generator for a professor.
Respond with ONLY valid JSON, no extra text, no markdown fences.
Every question must include "source_chunk" and "bloom_level" (which
must be exactly "{bloom_level}").
{format_instruction}"""

    user_prompt = f"""Generate {num_questions} {difficulty}-difficulty
{question_type} questions at Bloom's Taxonomy level "{bloom_level}"
({bloom_guidance.get(bloom_level, "")}) based on the numbered course
material below.

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

    # Minimal contract guard; full question validation belongs to a later build.
    if not isinstance(questions, list) or len(questions) != num_questions:
        print("Invalid question response: expected the requested number of questions.")
        return None
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("question"), str) or not q["question"].strip():
            print("Invalid question response: missing question text.")
            return None
        if question_type == "MCQ":
            options = q.get("options")
            if not isinstance(options, dict) or set(options) != {"A", "B", "C", "D"} or any(not isinstance(v, str) or not v.strip() for v in options.values()) or not isinstance(q.get("correct_answer"), str) or q["correct_answer"] not in options:
                print("Invalid question response: malformed MCQ options or answer.")
                return None
        elif not isinstance(q.get("model_answer"), str) or not q["model_answer"].strip():
            print("Invalid question response: missing model answer.")
            return None
        chunk_index = q.get("source_chunk")
        if chunk_index is not None and (type(chunk_index) is not int or not 0 <= chunk_index < len(metadatas)):
            print("Invalid question response: invalid source_chunk index.")
            return None
        if chunk_index is not None:
            meta = metadatas[chunk_index] or {}
            q["source_label"] = f"{meta.get('source', 'Unknown')} ({meta.get('unit', 'Unassigned')})"
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


def generate_personalized_practice(flagged_students_df, source_name, course=None):
    """
    For each struggling student (from Analytics), generates a short,
    easier-difficulty practice quiz at a foundational Bloom's level —
    directly targeting the students who need reinforcement most.

    Returns: [{"student_name": ..., "questions": [...]}, ...]
    """
    if 'practice_eligible' in flagged_students_df:
        flagged_students_df = flagged_students_df.loc[flagged_students_df['practice_eligible']]
    practice_sets = []

    for _, row in flagged_students_df.iterrows():
        questions = generate_questions(
            source_name=source_name,
            course=course,
            num_questions=3,
            question_type="MCQ",
            difficulty="Easy",
            bloom_level="Remember"
        )

        practice_sets.append({
            "student_name": row["student_name"],
            "questions": questions
        })

    return practice_sets

def generate_question_paper(
    source_name=None,
    course=None,
    num_mcq=5,
    num_descriptive=2,
    marks_per_mcq=2,
    marks_per_descriptive=5,
    difficulty="Medium"
):
    """
    Generates a full question paper combining MCQs and descriptive
    questions, with marks assigned to each, plus a total marks summary —
    exactly what a professor needs to assemble a real test.
    """
    paper = {"mcq_section": [], "descriptive_section": [], "total_marks": 0}

    if num_mcq > 0:
        mcqs = generate_questions(
            source_name=source_name,
            course=course,
            num_questions=num_mcq,
            question_type="MCQ",
            difficulty=difficulty
        )
        if mcqs:
            for q in mcqs:
                q["marks"] = marks_per_mcq
            paper["mcq_section"] = mcqs
            paper["total_marks"] += marks_per_mcq * len(mcqs)

    if num_descriptive > 0:
        descriptive = generate_questions(
            source_name=source_name,
            course=course,
            num_questions=num_descriptive,
            question_type="Descriptive",
            difficulty=difficulty
        )
        if descriptive:
            for q in descriptive:
                q["marks"] = marks_per_descriptive
            paper["descriptive_section"] = descriptive
            paper["total_marks"] += marks_per_descriptive * len(descriptive)

    return paper