# 🎓 EduAgent — Multi-Agent AI Assistant for Higher Education

**Author:** Vinod Sahu
**Course/Project:** Minor Project

## Overview

EduAgent is a multi-agent AI system that assists professors and students
with common academic tasks — reading course material, answering student
questions, generating quizzes, drafting institutional documents, and
analyzing student performance. Each task is handled by a specialized
"agent," and a coordinator routes requests to the right one.

The system runs **entirely locally** using an open-source LLM
(via Ollama), so there is no dependency on a paid API and no student
data ever leaves the machine — an important property for an
educational tool handling academic content and student records.

## Architecture

                ┌─────────────────────┐
                │   Coordinator (UI)  │
                │   Streamlit sidebar │
                └──────────┬──────────┘
                           │
     ┌──────────┬──────────┼──────────┬──────────┐
     ▼          ▼          ▼          ▼          ▼
    ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
    │Content │ │Student │ │Assess- │ │Document│ │Analytics│
    │ Agent  │ │Support │ │ment │ │ Agent │ │ Agent │
    │ │ │ Agent │ │ Agent │ │ │ │ │
    └───┬────┘ └───┬────┘ └────────┘ └────────┘ └────────┘
│ │
▼ ▼
┌────────────────────┐
│ ChromaDB (Vector │
│ Database) — stores │
│ embedded chunks of │
│ course material │
└────────────────────┘

## Agents

| Agent | Function |
|---|---|
| **Content Agent** | Extracts text from uploaded PDFs and splits it into searchable chunks |
| **Student Support Agent** | Answers student questions using Retrieval-Augmented Generation (RAG) — grounded only in uploaded course material |
| **Assessment Agent** | Generates multiple-choice quizzes with an answer key from course content |
| **Document Agent** | Drafts notices, circulars, and emails in institutional format |
| **Analytics Agent** | Analyzes marks/attendance CSVs and flags students who may need academic support |
| **Coordinator** | Routes requests to the correct agent via the app's sidebar navigation |

## Tech Stack

- **Language:** Python
- **UI:** Streamlit
- **LLM:** Llama 3.2 (via Ollama — runs 100% locally, no API costs)
- **Vector Database:** ChromaDB
- **Embeddings:** sentence-transformers (all-MiniLM-L6-v2)
- **PDF Parsing:** pdfplumber
- **Data Analysis:** pandas

## Concepts Demonstrated

- **NLP & RAG:** Retrieval-Augmented Generation grounds LLM answers in
  real course material instead of relying on the model's general
  knowledge, reducing hallucination.
- **Multi-Agent Systems:** Each agent is an independently callable,
  specialized module with a single responsibility — a lightweight
  version of the agent-based architectures used in production AI systems.
- **Vector Databases:** Text is converted into embeddings and stored in
  ChromaDB, enabling semantic (meaning-based) search rather than
  keyword matching.
- **Software Engineering:** Modular file structure, environment
  isolation (`venv`), version control (Git/GitHub), and separation of
  concerns between agents.
- **Data Analysis:** Pandas-based processing of structured academic
  data (marks, attendance) to surface actionable insights.

## How to Run

1. Clone this repository
2. Create a virtual environment: `python3 -m venv venv && source venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Install [Ollama](https://ollama.com) and pull a model: `ollama pull llama3.2:3b`
5. Run the app: `streamlit run app.py`

## Future Scope

- Smarter coordinator that routes free-text requests using LLM intent
  classification instead of manual navigation
- Bloom's Taxonomy-tagged question generation
- CO-PO mapping for accreditation requirements
- Rubric and evaluation report generation
- Google Classroom-ready export formats