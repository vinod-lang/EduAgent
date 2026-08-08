import ollama

MODEL_NAME = "llama3.2:3b"


# Each template defines: the fields it needs, and how to turn those
# fields into an instruction for the LLM
TEMPLATES = {
    "Notice": {
        "fields": ["course", "subject", "details", "date"],
        "build_instruction": lambda f: (
            f"Write a formal notice for the course '{f['course']}' "
            f"about: {f['subject']}. Details: {f['details']}. "
            f"Relevant date: {f['date']}."
        )
    },
    "Circular": {
        "fields": ["subject", "audience", "details", "date"],
        "build_instruction": lambda f: (
            f"Write a formal circular addressed to {f['audience']} "
            f"regarding: {f['subject']}. Details: {f['details']}. "
            f"Effective/relevant date: {f['date']}."
        )
    },
    "Attendance Warning": {
        "fields": ["student_name", "course", "attendance_percent", "required_percent"],
        "build_instruction": lambda f: (
            f"Write a formal attendance warning letter addressed to student "
            f"{f['student_name']} for the course '{f['course']}'. Their "
            f"current attendance is {f['attendance_percent']}%, which is "
            f"below the required {f['required_percent']}%. Ask them to "
            f"improve attendance and mention they may contact the "
            f"department if there are genuine reasons."
        )
    },
    "Exam Announcement": {
        "fields": ["course", "exam_date", "exam_time", "venue", "details"],
        "build_instruction": lambda f: (
            f"Write a formal exam announcement for the course '{f['course']}'. "
            f"Exam date: {f['exam_date']}, time: {f['exam_time']}, "
            f"venue: {f['venue']}. Additional details: {f['details']}."
        )
    }
}


def generate_document(template_name, field_values):
    """
    Drafts a document using a structured template instead of free text.

    template_name: one of the keys in TEMPLATES
    field_values: a dictionary matching that template's required fields
    """
    template = TEMPLATES[template_name]
    instruction = template["build_instruction"](field_values)

    system_prompt = f"""You are an assistant that drafts official {template_name}s
for a college/university. Write in a formal, professional tone.
Include a clear title, a date placeholder if no date was given,
the body content, and a closing line with a designation placeholder
(e.g. "Head of Department"). Output ONLY the document text —
no commentary before or after."""

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": instruction}
        ]
    )

    return response["message"]["content"]


if __name__ == "__main__":
    doc = generate_document("Attendance Warning", {
        "student_name": "Priya Patel",
        "course": "Machine Learning",
        "attendance_percent": "65",
        "required_percent": "75"
    })
    print(doc)

def generate_batch_attendance_warnings(flagged_students_df, course_name="General", required_percent="75"):
    """
    Takes a DataFrame of flagged students (from the Analytics Agent)
    and generates one personalized attendance warning letter per student.

    Returns a list of dicts: [{"student_name": ..., "document": ...}, ...]
    """
    generated_letters = []

    for _, row in flagged_students_df.iterrows():
        field_values = {
            "student_name": row["student_name"],
            "course": course_name,
            "attendance_percent": str(row["latest_attendance"]),
            "required_percent": required_percent
        }

        letter = generate_document("Attendance Warning", field_values)

        generated_letters.append({
            "student_name": row["student_name"],
            "document": letter
        })

    return generated_letters