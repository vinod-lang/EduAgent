"""Managed academic-file lifecycle. SQLite ownership survives failed external cleanup.

No distributed transaction exists: compensations and partial failures are explicit.
Legacy vectors/files are never adopted or deleted automatically.
"""
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
import db
from chunking import chunk_text
from content_agent import extract_content
from config import get_max_upload_bytes, ConfigurationError

EXTENSIONS = ('.pdf', '.png', '.jpg', '.jpeg')

LEVELS = ('course', 'semester', 'subject', 'unit')


class MaterialError(ValueError):
    pass


def hierarchy_values(values):
    result = {}
    for key in LEVELS:
        value = values.get(key)
        if not isinstance(value, str) or not value.strip():
            raise MaterialError(f'{key.capitalize()} is required.')
        result[key] = value.strip()
    return result


def content_hash(data):
    return hashlib.sha256(data).hexdigest()


def validate_filename(name):
    if not isinstance(name, str) or not name or name in ('.', '..') or '/' in name or '\\' in name or any(ord(c) < 32 for c in name) or ':' in name:
        raise MaterialError('Use an original filename without paths or control characters.')
    if Path(name).suffix.lower() not in EXTENSIONS:
        raise MaterialError('Supported materials are PDF, PNG, JPG and JPEG.')
    return name


def owned_ids(record):
    try:
        ids = json.loads(record['chunk_ids'])
    except (ValueError, TypeError, KeyError) as exc:
        raise MaterialError('Invalid recorded chunk ownership.') from exc
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise MaterialError('Invalid recorded chunk ownership.')
    expected = [f"{record['material_id']}_chunk_{i}" for i in range(len(ids))]
    if ids != expected:
        raise MaterialError('Chunk ownership does not match the managed material UUID.')
    return ids


def managed_path(record, uploads):
    try:
        identity = str(uuid.UUID(record['material_id']))
    except (ValueError, KeyError, TypeError) as exc:
        raise MaterialError('Not a managed UUID material.') from exc
    filename = record.get('managed_filename')
    if not isinstance(filename, str) or Path(filename).suffix not in EXTENSIONS or filename != identity + Path(filename).suffix:
        raise MaterialError('Unsafe managed filename.')
    root = Path(uploads).resolve()
    candidate = root / filename
    if candidate.is_symlink() or candidate.resolve().parent != root:
        raise MaterialError('Managed file path escapes storage or is a symlink.')
    return candidate


def vectors_api(vectors):
    if vectors is None:
        import vector_store
        return vector_store
    return vectors


def result(success=False, **fields):
    return dict(success=success, warnings=[], **fields)


def upload_material(data, original_filename, hierarchy, *, uploads='uploads', vectors=None, extractor=None, ownership_metadata=None):
    name = validate_filename(original_filename)
    hierarchy = hierarchy_values(hierarchy)
    if not isinstance(data, bytes) or not data:
        raise MaterialError('Upload must contain nonempty file bytes.')
    try:
        limit = get_max_upload_bytes()
    except ConfigurationError as exc:
        raise MaterialError(str(exc)) from exc
    if len(data) > limit:
        raise MaterialError(f'Upload exceeds the {limit / 1024 / 1024:g} MB size limit.')
    authorization={};ownership=None
    if ownership_metadata is not None:
        from security.models import Ownership,Scope
        try:
            value=dict(ownership_metadata)
            ownership=Ownership(value.pop('owner_professor_id'),value.pop('institution_id'),Scope(value.pop('visibility_scope')),value.pop('department_id',None),value.pop('course_id',None))
            authorization=ownership.vector_metadata()
            if value:raise ValueError('Unsupported ownership fields.')
        except (ValueError,TypeError,KeyError) as exc:raise MaterialError('Invalid ownership metadata.') from exc
    digest = content_hash(data)
    try:
        duplicate = db.find_material_hash(digest)
    except Exception as exc:
        return result(error=f'Material registry is unavailable: {exc}')
    if duplicate:
        return result(duplicate=True, existing_material=duplicate, error=f"Exact content already registered as {duplicate['original_filename']}.")
    identity = str(uuid.uuid4())
    record = dict(material_id=identity, original_filename=name, managed_filename=identity+Path(name).suffix.lower(), file_hash=digest, **hierarchy, created_at=datetime.now().isoformat())
    root = Path(uploads)
    path = managed_path(record, root)
    ids = []; created = False; attempted_vectors = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            created = True
            stream.write(data)
        text = extractor(path) if extractor is not None else extract_content(path)
        chunks = chunk_text(text)
        if not chunks:
            raise MaterialError('Material contains no usable extracted text.')
        ids = [f'{identity}_chunk_{i}' for i in range(len(chunks))]
        record['chunk_ids'] = json.dumps(ids)
        metadata = dict(material_id=identity, source=name, **hierarchy, **authorization)
        vectors = vectors_api(vectors)
        if vectors.get_material_chunks(ids)['ids']:
            raise MaterialError('Generated chunk IDs already exist; upload refused.')
        attempted_vectors = True
        vectors.add_material_chunks(ids, chunks, metadata)
        stored = checked_chunks(vectors, record, ids)
        if set(stored['ids']) != set(ids):
            raise MaterialError('Vector insertion did not persist every owned chunk.')
        db.register_material(record) if ownership is None else db.register_material(record,ownership=ownership)
        return result(True, material=record, vectors_created=len(ids),
                      text_preview=text[:1000] if Path(name).suffix.lower() != '.pdf' else '')
    except Exception as exc:
        warnings = []
        if attempted_vectors:
            try:
                vectors.delete_material_chunks(ids)
                if vectors.get_material_chunks(ids)['ids']:
                    raise MaterialError('Vector rollback could not be verified.')
            except Exception as cleanup:
                warnings.append(f'Vector rollback failed: {cleanup}; retry IDs: {ids}')
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError as cleanup:
                warnings.append(f'File rollback failed: {cleanup}; material ID: {identity}')
        out = result(error=f'Upload failed: {exc}', material_id=identity, chunk_ids=ids)
        # A concurrent upload can win the UNIQUE hash race; keep this controlled.
        try:
            duplicate = db.find_material_hash(digest)
            if duplicate:
                out.update(duplicate=True, existing_material=duplicate,
                           error=f"Exact content already registered as {duplicate['original_filename']}.")
        except Exception:
            # Preserve the original failure and recovery details if storage is down.
            out['warnings'].append('Registry could not be rechecked after upload failure.')
        out['warnings'].extend(warnings)
        return out


def check_ownership(record):
    ids = owned_ids(record)
    for other in db.list_materials():
        if other['material_id'] == record['material_id']:
            continue
        try:
            other_ids = json.loads(other['chunk_ids'])
        except (ValueError, TypeError) as exc:
            raise MaterialError('Cannot verify ownership: another registry record is corrupt.') from exc
        if not isinstance(other_ids, list) or any(not isinstance(i, str) for i in other_ids):
            raise MaterialError('Cannot verify ownership: another registry record is corrupt.')
        if set(ids).intersection(other_ids) or other['managed_filename'] == record['managed_filename']:
            raise MaterialError('Shared vector/file ownership: cleanup refused.')
    return ids


def checked_chunks(vectors, record, ids):
    chunks = vectors.get_material_chunks(ids)
    returned_ids = chunks.get('ids', [])
    metadatas = chunks.get('metadatas')
    if not isinstance(metadatas, list) or len(metadatas) != len(returned_ids) or not set(returned_ids).issubset(ids):
        raise MaterialError('Vector lookup returned inconsistent ownership data.')
    for metadata in metadatas:
        if not metadata or metadata.get('material_id') != record['material_id']:
            raise MaterialError('Vector ownership metadata does not match material.')
    return chunks


def delete_material(material_id, *, uploads='uploads', vectors=None):
    out = result(sqlite_deleted=False, vectors_deleted=0, file_deleted=False)
    try:
        record = db.get_material(material_id)
        if not record:
            raise MaterialError('Managed material not found; legacy deletion is not supported.')
        ids = check_ownership(record)
        path = managed_path(record, uploads)
        vectors = vectors_api(vectors)
        existing = checked_chunks(vectors, record, ids)
        vectors.delete_material_chunks(ids)
        if vectors.get_material_chunks(ids)['ids']:
            raise MaterialError('Vector deletion could not be verified.')
        out['vectors_deleted'] = len(existing['ids'])
        if path.exists():
            path.unlink()
            out['file_deleted'] = True
        else:
            out['warnings'].append('Managed file was already missing.')
        db.remove_material_record(material_id)
        out.update(success=True, sqlite_deleted=True)
    except Exception as exc:
        out['error'] = f'Deletion incomplete; registry retained for retry when present: {exc}'
    return out


def edit_hierarchy(material_id, hierarchy, *, vectors=None):
    values = hierarchy_values(hierarchy)
    previous = None
    try:
        record = db.get_material(material_id)
        if not record:
            raise MaterialError('Managed material not found; legacy editing is not supported.')
        vectors = vectors_api(vectors)
        ids = check_ownership(record)
        previous = checked_chunks(vectors, record, ids)
        if set(previous['ids']) != set(ids):
            raise MaterialError('Material has missing chunks; repair is required before editing.')
        updated = [dict(meta, **values) for meta in previous['metadatas']]
        vectors.update_material_chunks(previous['ids'], updated)
        persisted = checked_chunks(vectors, record, ids)
        if set(persisted['ids']) != set(ids) or any(any(meta.get(k) != v for k, v in values.items()) for meta in persisted['metadatas']):
            raise MaterialError('Vector hierarchy update could not be verified.')
        db.update_material_hierarchy(material_id, values)
        return result(True, material_id=material_id)
    except Exception as exc:
        out = result(error=f'Hierarchy update failed: {exc}')
        if previous:
            try:
                vectors.update_material_chunks(previous['ids'], previous['metadatas'])
            except Exception as rollback:
                out['warnings'].append(f'Vector metadata rollback failed: {rollback}')
        return out
