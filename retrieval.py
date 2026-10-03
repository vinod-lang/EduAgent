"""Deterministic retrieval; no generation, embedding changes or persisted questions."""
from collections.abc import Mapping
from dataclasses import dataclass, asdict
import math
from pathlib import PurePath
import re
import unicodedata
from config import ConfigurationError
from retrieval_config import get_retrieval_config

FILTER_KEYS = ('course', 'semester', 'subject', 'unit', 'material_id', 'source')

class RetrievalError(ValueError):
    pass


def normalize_filters(filters=None):
    if filters is None:
        return {}
    if not isinstance(filters, Mapping) or any(key not in FILTER_KEYS for key in filters):
        raise RetrievalError('Unsupported retrieval filter. Use course, semester, subject, unit, material_id or source.')
    normalized = {}
    for key, value in filters.items():
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise RetrievalError(f'{key} filter must be nonblank text.')
        normalized[key] = value.strip()
    return {key: normalized[key] for key in FILTER_KEYS if key in normalized}


def build_filter(filters=None):
    values = normalize_filters(filters)
    clauses = [{key: value} for key, value in values.items()]
    return {'$and': clauses} if len(clauses) > 1 else clauses[0] if clauses else None


def text_value(metadata, key):
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    text: str
    distance: float
    material_id: str | None = None
    source: str = 'Unknown'
    course: str | None = None
    semester: str | None = None
    subject: str | None = None
    unit: str | None = None
    page: int | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class EvidenceSource:
    material_id: str | None
    source: str
    course: str | None
    semester: str | None
    subject: str | None
    unit: str | None
    page: int | None
    content_type: str | None

    @property
    def label(self):
        label = f'{self.source} ({self.unit or "Unassigned"})'
        hierarchy = [value for value in (self.course, self.semester, self.subject) if value]
        if hierarchy:
            label += ' — ' + ' → '.join(hierarchy)
        if self.page is not None:
            label += f' — Page {self.page}'
        return label


@dataclass(frozen=True)
class RetrievalDiagnostics:
    candidates_requested: int
    candidates_returned: int
    invalid_results: int
    duplicates_removed: int
    relevance_rejected: int
    evidence_used: int
    active_filters: dict
    metric: str
    max_distance: float

    def to_dict(self):
        return asdict(self)  # counts/settings only; no evidence text or query


@dataclass(frozen=True)
class RetrievalResult:
    evidence: tuple[EvidenceChunk, ...]
    diagnostics: RetrievalDiagnostics

    @property
    def status(self):
        return 'evidence_found' if self.evidence else 'no_evidence'

    @property
    def sources(self):
        sources = []
        seen = set()
        for chunk in self.evidence:
            identity = (chunk.material_id or chunk.source, chunk.course, chunk.semester, chunk.subject, chunk.unit, chunk.page)
            if identity in seen:
                continue
            seen.add(identity)
            sources.append(EvidenceSource(chunk.material_id, chunk.source, chunk.course, chunk.semester, chunk.subject, chunk.unit, chunk.page, chunk.content_type))
        return tuple(sources)


def collection_metric(collection):
    # Never apply a cosine cutoff to a different/unknown index metric.
    configuration = collection.configuration
    if isinstance(configuration, Mapping):
        for index in ('hnsw', 'spann'):
            settings = configuration.get(index)
            if isinstance(settings, Mapping) and settings.get('space'):
                return settings['space']
    raise RetrievalError('Collection distance metric is unavailable; retrieval refused.')


def first_batch(raw, key, *, required=False):
    value = raw.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, (list, tuple)) or len(value) != 1 or not isinstance(value[0], (list, tuple)):
        raise RetrievalError(f'Retrieval returned malformed {key}.')
    return value[0]


def normalize_results(raw):
    if not isinstance(raw, Mapping):
        raise RetrievalError('Retrieval returned an unusable response.')
    ids = first_batch(raw, 'ids', required=True)
    documents = first_batch(raw, 'documents', required=True)
    distances = first_batch(raw, 'distances', required=True)
    metadata = first_batch(raw, 'metadatas')
    if len(ids) != len(documents) or len(ids) != len(distances) or (metadata and len(metadata) != len(ids)):
        raise RetrievalError('Retrieval returned mismatched chunk data.')
    chunks = []; invalid = 0
    for index, (identity, text, distance) in enumerate(zip(ids, documents, distances)):
        # Chroma floating-point roundoff may produce a tiny negative cosine distance.
        if not isinstance(identity, str) or not identity or not isinstance(text, str) or not text.strip() or isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(distance) or distance < -1e-6 or distance > 2.000001:
            invalid += 1
            continue
        meta = metadata[index] if metadata else {}
        meta = meta if isinstance(meta, Mapping) else {}
        source = text_value(meta, 'original_filename') or text_value(meta, 'source') or 'Unknown'
        content_type = text_value(meta, 'content_type')
        extension = PurePath(source).suffix.lower()
        if extension in ('.png', '.jpg', '.jpeg'):
            content_type = 'Image/OCR'
        elif extension == '.pdf' and not content_type:
            content_type = 'PDF'
        page = meta.get('page')
        image_type = bool(content_type and (content_type.lower().startswith('image') or content_type.lower() == 'ocr'))
        if type(page) is not int or page < 1 or image_type:
            page = None
        chunks.append(EvidenceChunk(identity, text.strip(), max(0., float(distance)),
                        text_value(meta, 'material_id'), source,
                        *[text_value(meta, key) for key in ('course', 'semester', 'subject', 'unit')], page, content_type))
    return chunks, invalid, len(ids)


def deduplicate(chunks):
    ids = set(); texts = set(); selected = []
    for chunk in chunks:
        normalized = re.sub(r'\s+', ' ', unicodedata.normalize('NFC', chunk.text)).strip()
        if chunk.chunk_id in ids or normalized in texts:
            continue
        ids.add(chunk.chunk_id); texts.add(normalized); selected.append(chunk)
    return selected, len(chunks) - len(selected)


def retrieve_evidence(query, filters=None, *, candidate_k=None, final_k=None, max_distance=None, collection=None):
    if not isinstance(query, str) or not query.strip():
        raise RetrievalError('Question must be nonblank text.')
    values = normalize_filters(filters)
    try:
        settings = get_retrieval_config(candidate_k=candidate_k, final_k=final_k, max_distance=max_distance)
    except ConfigurationError as exc:
        raise RetrievalError(str(exc)) from exc
    try:
        if collection is None:
            from vector_store import collection
        metric = collection_metric(collection)
        if metric != 'cosine':
            raise RetrievalError(f'RAG v2 requires cosine distance; this collection uses {metric}. No index was changed.')
        # Empty collections need no embedding call; scoped emptiness returns an empty batch.
        if collection.count() == 0:
            return RetrievalResult((), RetrievalDiagnostics(settings.candidate_k, 0, 0, 0, 0, 0, values, metric, settings.max_distance))
        raw = collection.query(query_texts=[query], n_results=settings.candidate_k,
                               where=build_filter(values), include=['documents', 'metadatas', 'distances'])
        chunks, invalid, returned = normalize_results(raw)
        # Chroma ranks nearest first. Stable distance sorting also protects adapters
        # returning out-of-order rows: retain the closest copy of duplicate evidence.
        chunks.sort(key=lambda chunk: chunk.distance)
        unique, duplicates = deduplicate(chunks)
        relevant = [chunk for chunk in unique if chunk.distance <= settings.max_distance]
        evidence = tuple(relevant[:settings.final_k])
        return RetrievalResult(evidence, RetrievalDiagnostics(settings.candidate_k, returned, invalid, duplicates,
                               len(unique) - len(relevant), len(evidence), values, metric, settings.max_distance))
    except RetrievalError:
        raise
    except Exception as exc:
        raise RetrievalError('Course-material retrieval failed. Check local storage and embedding availability.') from exc
