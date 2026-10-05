import sqlite3
from contextlib import contextmanager
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
    init_material_schema()


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

@contextmanager
def material_connection():
    conn = get_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# Managed materials coexist with the untouched legacy documents registry.
def init_material_schema():
    with material_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS materials (
            material_id TEXT PRIMARY KEY,
            original_filename TEXT NOT NULL,
            managed_filename TEXT UNIQUE NOT NULL,
            file_hash TEXT UNIQUE NOT NULL,
            course TEXT NOT NULL, semester TEXT NOT NULL,
            subject TEXT NOT NULL, unit TEXT NOT NULL,
            chunk_ids TEXT NOT NULL, created_at TEXT NOT NULL
        )''')


def get_material(material_id):
    with material_connection() as conn:
        row = conn.execute('SELECT * FROM materials WHERE material_id = ?', (material_id,)).fetchone()
        return dict(row) if row else None


def find_material_hash(file_hash):
    with material_connection() as conn:
        row = conn.execute('SELECT * FROM materials WHERE file_hash = ?', (file_hash,)).fetchone()
        return dict(row) if row else None


def list_materials(course=None):
    with material_connection() as conn:
        rows = conn.execute('SELECT * FROM materials' + (' WHERE course = ?' if course else '') + ' ORDER BY created_at DESC', (course,) if course else ()).fetchall()
        return [dict(row) for row in rows]


def register_material(record):
    keys = ('material_id', 'original_filename', 'managed_filename', 'file_hash', 'course', 'semester', 'subject', 'unit', 'chunk_ids', 'created_at')
    with material_connection() as conn:
        conn.execute('INSERT INTO materials (' + ','.join(keys) + ') VALUES (' + ','.join('?' for _ in keys) + ')', tuple(record[k] for k in keys))
        conn.execute('INSERT OR IGNORE INTO courses (course_name, created_at) VALUES (?, ?)', (record['course'], record['created_at']))
        conn.execute('INSERT INTO activity_log (action, details, timestamp) VALUES (?, ?, ?)', ('material_uploaded', record['material_id'], record['created_at']))


def update_material_hierarchy(material_id, hierarchy):
    with material_connection() as conn:
        conn.execute('UPDATE materials SET course=?, semester=?, subject=?, unit=? WHERE material_id=?', (*[hierarchy[k] for k in ('course','semester','subject','unit')], material_id))
        conn.execute('INSERT OR IGNORE INTO courses (course_name, created_at) VALUES (?, ?)', (hierarchy['course'], datetime.now().isoformat()))
        conn.execute('INSERT INTO activity_log (action, details, timestamp) VALUES (?, ?, ?)', ('material_hierarchy_updated', material_id, datetime.now().isoformat()))


def remove_material_record(material_id):
    with material_connection() as conn:
        conn.execute('DELETE FROM materials WHERE material_id=?', (material_id,))
        conn.execute('INSERT INTO activity_log (action, details, timestamp) VALUES (?, ?, ?)', ('material_deleted', material_id, datetime.now().isoformat()))


def legacy_materials(course):
    return [dict(row, semester='Unassigned', subject='Unassigned', unit=row.get('unit') or 'Unassigned', managed=False) for row in get_documents_for_course(course)]


def assessment_legacy_scope_records():
    """Read only recorded legacy hierarchy; do not invent semester/subject values."""
    with material_connection() as conn:
        columns={row['name'] for row in conn.execute('PRAGMA table_info(documents)')}
        if not {'course','semester','subject','unit'}<=columns:
            return []
        return [dict(row) for row in conn.execute('SELECT * FROM documents')]
