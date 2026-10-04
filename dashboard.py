"""SQLite-only professor overview. Never counts unregistered Chroma vectors."""
from collections import Counter
from pathlib import Path
from datetime import datetime
import db

# Only known actions are displayed; arbitrary log text may contain private data.
ACTIONS = {
    'assessment_generated': 'Assessment generated',
    'material_uploaded': 'Material uploaded',
    'material_hierarchy_updated': 'Material hierarchy updated',
    'material_deleted': 'Material deleted',
    'generate_quiz': 'Quiz generated',
    'generate_question_paper': 'Question paper generated',
    'batch_warnings': 'Attendance warning batch generated',
    'personalized_practice': 'Practice batch generated',
    'generate_document': 'Document generated',
    'document_generated': 'Document generated',
    'document_saved': 'Document saved',
    'document_version_created': 'Document version saved',
    'document_feedback_saved': 'Document feedback saved',
    'preference_approved': 'Preference approved',
    'preference_updated': 'Preference updated',
    'preference_disabled': 'Preference disabled',
    'preference_deleted': 'Preference deleted',
}
PAGES = ('Professor Dashboard', 'Upload Content', 'Ask a Question', 'Assessment Studio', 'Document Studio', 'Analytics', 'Activity Log')
QUICK_ACTIONS = {
    'Upload Content': 'Upload Content',
    'Ask Knowledge Base': 'Ask a Question',
    'Create Assessment': 'Assessment Studio',
    'Create Document': 'Document Studio',
    'Analyze Students': 'Analytics',
    'View Activity': 'Activity Log',
}


def material_type(material):
    return 'Image/OCR' if Path(material.get('original_filename', '')).suffix.lower() in ('.png', '.jpg', '.jpeg') else 'PDF'


def get_dashboard_summary():
    courses = db.get_all_courses()
    materials = db.list_materials()
    with db.material_connection() as conn:
        legacy_count = conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
    activity = get_activity_view(limit=5)
    counts = Counter(m['course'] for m in materials)
    return dict(course_count=len(courses), managed_count=len(materials), legacy_count=legacy_count,
                materials_by_course={course: counts[course] for course in sorted(set(courses) | set(counts))},
                recent_materials=materials[:5], recent_activity=activity)


def get_activity_view(limit=20):
    """Sanitize existing log entries identically on Dashboard and Activity Log."""
    activity = []
    for entry in db.get_recent_activity(limit=limit):
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
    return activity


def natural_key(value):
    import re
    # Tagged components avoid comparing integers with text; original spelling
    # breaks case-fold ties deterministically, including Unicode names.
    return (tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                  for part in re.split(r'(\d+)', value)), value)


def build_material_tree(materials, courses=()):
    """Course → Semester → Subject → Unit → original material records.

    Only authoritative managed records enter this tree. Empty registered courses
    remain visible; legacy records are presented separately without invented levels.
    """
    tree = {course: {} for course in courses}
    for material in materials:
        branch = tree.setdefault(material['course'], {})
        for level in ('semester', 'subject'):
            branch = branch.setdefault(material[level], {})
        branch.setdefault(material['unit'], []).append(material)

    def ordered(branch):
        if isinstance(branch, list):
            return sorted(branch, key=lambda material: (natural_key(material['original_filename']), material.get('created_at') or '', material['material_id']))
        return {key: ordered(branch[key]) for key in sorted(branch, key=natural_key)}
    return ordered(tree)


def legacy_content_view():
    """Read-only registry projection; does not claim vectors or managed ownership."""
    with db.material_connection() as conn:
        rows = conn.execute('SELECT source_name, course, unit, uploaded_at FROM documents ORDER BY course, source_name, id').fetchall()
        return [dict(row) for row in rows]
