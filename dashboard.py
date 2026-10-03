"""SQLite-only professor overview. Never counts unregistered Chroma vectors."""
from collections import Counter
from pathlib import Path
from datetime import datetime
import db

# Only known actions are displayed; arbitrary log text may contain private data.
ACTIONS = {
    'material_uploaded': 'Material uploaded',
    'material_hierarchy_updated': 'Material hierarchy updated',
    'material_deleted': 'Material deleted',
    'generate_quiz': 'Quiz generated',
    'generate_question_paper': 'Question paper generated',
    'batch_warnings': 'Attendance warning batch generated',
    'personalized_practice': 'Practice batch generated',
    'generate_document': 'Document generated',
}
QUICK_ACTIONS = ('Upload Content', 'Ask a Question', 'Generate Quiz',
                 'Question Paper', 'Draft Document', 'Analytics', 'Courses & Activity')


def material_type(material):
    return 'Image/OCR' if Path(material.get('original_filename', '')).suffix.lower() in ('.png', '.jpg', '.jpeg') else 'PDF'


def get_dashboard_summary():
    courses = db.get_all_courses()
    materials = db.list_materials()
    with db.material_connection() as conn:
        legacy_count = conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
    activity = []
    for entry in db.get_recent_activity(limit=5):
        if not isinstance(entry, dict):
            entry = {}
        timestamp = entry.get('timestamp')
        # Parse, rather than echo arbitrary strings stored in old logs.
        try:
            timestamp = datetime.fromisoformat(timestamp).strftime('%Y-%m-%d %H:%M')
        except (TypeError, ValueError):
            timestamp = 'Time unavailable'
        action = entry.get('action')
        label = ACTIONS.get(action, 'Recorded activity') if isinstance(action, str) else 'Recorded activity'
        activity.append({'action': label, 'timestamp': timestamp})
    counts = Counter(m['course'] for m in materials)
    return dict(course_count=len(courses), managed_count=len(materials), legacy_count=legacy_count,
                materials_by_course={course: counts[course] for course in sorted(set(courses) | set(counts))},
                recent_materials=materials[:5], recent_activity=activity)
