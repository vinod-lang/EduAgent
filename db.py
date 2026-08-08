import sqlite3
from datetime import datetime

DB_PATH = "eduagent.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us access columns by name
    return conn


def init_db():
    """
    Creates all tables if they don't already exist.
    Safe to call every time the app starts — CREATE TABLE IF NOT EXISTS
    won't touch data that's already there.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT UNIQUE NOT NULL,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            course TEXT,
            unit TEXT,
            filename TEXT,
            uploaded_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details TEXT,
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()


def add_course_if_new(course_name):
    """Adds a course to the list if it doesn't already exist."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO courses (course_name, created_at) VALUES (?, ?)",
        (course_name, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_all_courses():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT course_name FROM courses ORDER BY course_name")
    rows = cursor.fetchall()
    conn.close()
    return [row["course_name"] for row in rows]


def add_document_record(source_name, course, unit, filename):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO documents (source_name, course, unit, filename, uploaded_at)
           VALUES (?, ?, ?, ?, ?)""",
        (source_name, course, unit, filename, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_documents_for_course(course_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM documents WHERE course = ? ORDER BY uploaded_at DESC",
        (course_name,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def log_activity(action, details=""):
    """
    Records every meaningful AI action — this is your audit trail,
    directly answering the 'accountability' requirement from the plan.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO activity_log (action, details, timestamp) VALUES (?, ?, ?)",
        (action, details, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_recent_activity(limit=20):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]