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
Actiavate virtual environment : source .venv-rebuild/bin/activate
5. Run the app: `streamlit run app.py`


Terminal 1 :
ollama list
ollama serve

Terminal 2:
cd ~/Desktop/EduAgent
source .venv-rebuild/bin/activate

export EDUAGENT_API_MODE=development
export EDUAGENT_DEV_AUTH=true
export EDUAGENT_DEV_IDENTITIES='{"professor-a":"a176c532-edce-447e-95ea-555c09bc9117","professor-b":"eac839ba-9366-4ba7-8aec-8dad06a0f808"}'
export EDUAGENT_DEV_ACCESS_KEY='bdde348890958366adc748285ef10546a2c3845fc3d31db66befc3b2a1833daf'
export EDUAGENT_API_ORIGINS='http://127.0.0.1:3000'
export EDUAGENT_API_DB="$PWD/.runtime/api-development.sqlite3"
export EDUAGENT_API_UPLOADS="$PWD/.runtime/uploads"
export EDUAGENT_API_CHROMA="$PWD/.runtime/chroma"

.venv-rebuild/bin/uvicorn api.app:create_api_app --factory --host 127.0.0.1 --port 8000

Terminal 3:
cd ~/Desktop/EduAgent/frontend

export EDUAGENT_API_BACKEND_URL='http://127.0.0.1:8000'
export EDUAGENT_FRONTEND_MODE=development
export EDUAGENT_FRONTEND_DEV_AUTH=true
export EDUAGENT_DEV_ALIASES='professor-a,professor-b'
export EDUAGENT_DEV_ACCESS_KEY='bdde348890958366adc748285ef10546a2c3845fc3d31db66befc3b2a1833daf'

npm run dev

http://127.0.0.1:3000


To check DEV ACCESS KEY :
cd ~/Desktop/EduAgent

if [ -n "$EDUAGENT_DEV_ACCESS_KEY" ]; then
  echo "Key is already set"
else
  echo "Key is NOT set"
fi

To generate DEV ACCESS KEY :
openssl rand -hex 32



## Future Scope

- Smarter coordinator that routes free-text requests using LLM intent
  classification instead of manual navigation
- Bloom's Taxonomy-tagged question generation
- CO-PO mapping for accreditation requirements
- Rubric and evaluation report generation
- Google Classroom-ready export formats