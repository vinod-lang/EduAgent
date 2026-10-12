import sqlite3
import db
import pytest

@pytest.fixture
def database(tmp_path,monkeypatch):
    path=tmp_path/"isolated.db"
    monkeypatch.setattr(db,"DB_PATH",str(path))
    db.init_db()
    return path

def test_initialization(database):
    db.init_db()
    conn=sqlite3.connect(database)
    try: assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {"courses","documents","activity_log"}
    finally: conn.close()

def test_duplicate_course(database):
    db.add_course_if_new("Synthetic Course");db.add_course_if_new("Synthetic Course")
    assert db.get_all_courses()==["Synthetic Course"]

def test_documents(database):
    db.add_document_record("synthetic","Synthetic Course","Unit 2","synthetic.pdf")
    db.add_document_record("other","Other Course","Unit 1","other.pdf")
    rows=db.get_documents_for_course("Synthetic Course")
    assert len(rows)==1
    assert rows[0]["unit"]=="Unit 2" and rows[0]["filename"]=="synthetic.pdf"

def test_activity(database):
    db.log_activity("synthetic_action","Synthetic details")
    assert db.get_recent_activity()[0]["action"]=="synthetic_action"
