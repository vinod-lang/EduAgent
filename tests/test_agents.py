import json
from unittest.mock import Mock
import pytest

def response(monkeypatch,module,value):
    mock=Mock(return_value=value)
    monkeypatch.setattr(module.ai_provider,"generate_chat",mock)
    return mock

def test_qa(agents,monkeypatch):
    module=agents["student_support_agent"]
    chat=response(monkeypatch,module,"Synthetic answer")
    answer,sources=module.answer_question("PCA?",n_chunks=4,course="Synthetic Course")
    agents["vectors"].search_database.assert_called_once_with("PCA?",n_results=15,course="Synthetic Course")
    assert answer=="Synthetic answer" and sources==["PCA (Unit 1)"]
    assert "Synthetic PCA context" in chat.call_args.kwargs["messages"][1]["content"]

def test_empty_qa(agents,monkeypatch):
    module=agents["student_support_agent"];chat=response(monkeypatch,module,"not used")
    agents["vectors"].search_database.return_value={"documents":[[]],"metadatas":[[]]}
    assert module.answer_question("Nothing")[1]==[]
    chat.assert_not_called()

@pytest.mark.parametrize("metadata", [{"source":"legacy"}, {}, None])
def test_legacy_qa(agents,monkeypatch,metadata):
    module=agents["student_support_agent"];response(monkeypatch,module,"fixture")
    agents["vectors"].search_database.return_value={"documents":[["Synthetic"]],"metadatas":[[metadata]]}
    assert "Unassigned" in module.answer_question("Question")[1][0]

def test_mcq_and_parameters(agents,monkeypatch,mcq):
    module=agents["assessment_agent"]
    chat=response(monkeypatch,module,json.dumps([mcq]))
    result=module.generate_questions("PCA",course="Synthetic",num_questions=1,difficulty="Easy",bloom_level="Remember")
    assert result[0]["correct_answer"]=="A" and result[0]["source_label"]=="PCA (Unit 1)"
    messages=chat.call_args.kwargs["messages"]
    assert "Easy-difficulty" in messages[1]["content"] and "Remember" in messages[0]["content"]
    assert "[Chunk 0] Synthetic PCA context" in messages[1]["content"]

def test_descriptive(agents,monkeypatch):
    module=agents["assessment_agent"]
    response(monkeypatch,module,json.dumps([{"question":"Describe synthetic PCA","model_answer":"Synthetic answer","source_chunk":0}]))
    assert module.generate_questions(num_questions=1,question_type="Descriptive")[0]["model_answer"]=="Synthetic answer"

@pytest.mark.parametrize("value", ["invalid", "{}", "[]", '[null]'])
def test_bad_output(agents,monkeypatch,value):
    module=agents["assessment_agent"];response(monkeypatch,module,value)
    assert module.generate_questions(num_questions=1) is None

@pytest.mark.parametrize("index", ["0",[],True,-1,999])
def test_bad_chunk_index(agents,monkeypatch,mcq,index):
    module=agents["assessment_agent"];mcq["source_chunk"]=index
    response(monkeypatch,module,json.dumps([mcq]))
    assert module.generate_questions(num_questions=1) is None

def test_wrong_count(agents,monkeypatch,mcq):
    module=agents["assessment_agent"];response(monkeypatch,module,json.dumps([mcq]))
    assert module.generate_questions(num_questions=3) is None

def test_paper(agents,monkeypatch,mcq):
    module=agents["assessment_agent"]
    desc={"question":"Synthetic describe","model_answer":"Synthetic answer","source_chunk":0}
    chat=Mock(side_effect=[json.dumps([mcq,mcq]),json.dumps([desc])])
    monkeypatch.setattr(module.ai_provider,"generate_chat",chat)
    paper=module.generate_question_paper(num_mcq=2,num_descriptive=1,marks_per_mcq=2,marks_per_descriptive=5)
    assert len(paper["mcq_section"])==2 and len(paper["descriptive_section"])==1
    assert paper["total_marks"]==9
    assert paper["mcq_section"][0]["correct_answer"]=="A"
    assert paper["descriptive_section"][0]["source_label"]=="PCA (Unit 1)"

def test_document(agents,monkeypatch):
    module=agents["document_agent"];chat=response(monkeypatch,module,"Synthetic notice")
    assert set(module.TEMPLATES)=={"Notice","Circular","Attendance Warning","Exam Announcement"}
    values={"course":"Synthetic CSE","subject":"Tutorial","details":"Lab 2","date":"10 October 2026"}
    assert module.generate_document("Notice",values)=="Synthetic notice"
    prompt=chat.call_args.kwargs["messages"][1]["content"]
    assert all(value in prompt for value in values.values())
    with pytest.raises(KeyError): module.generate_document("Notice",{})

@pytest.mark.parametrize("intent", ["question","quiz","document","quiz_and_notice"])
def test_classifier_supported(agents,monkeypatch,intent):
    module=agents["coordinator"];response(monkeypatch,module,intent)
    assert module.classify_intent("Synthetic request")==intent

def test_approval_unsupported(agents,monkeypatch):
    module=agents["coordinator"];response(monkeypatch,module,"approval_request")
    assert module.classify_intent("Synthetic approval")=="unknown"
