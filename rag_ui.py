"""SQLite-backed cascading controls; missing legacy hierarchy is never invented."""
import db


def available_courses(materials=None):
    records = db.list_materials() if materials is None else materials
    return sorted(set(db.get_all_courses()) | {row['course'] for row in records})


def scope_options(materials, filters, level):
    rows = [row for row in materials if all(row.get(key) == value for key, value in filters.items())]
    if level == 'material_id':
        return {row['material_id']: ' → '.join([row['original_filename'], row['course'], row['semester'], row['subject'], row['unit']])
                + (f" · Uploaded {row['created_at']}" if row.get('created_at') else '') for row in rows}
    return sorted({row[level] for row in rows if isinstance(row.get(level), str) and row[level]})
