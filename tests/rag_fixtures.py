"""Deterministic collection substitute with real exact-filter semantics."""
from copy import deepcopy

class Collection:
    configuration = {'hnsw': {'space': 'cosine'}}
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []
    def count(self): return len(self.rows)
    def query(self, query_texts, n_results, where=None, include=None):
        self.calls.append(dict(query_texts=query_texts, n_results=n_results, where=where, include=include))
        clauses = where.get('$and', [where]) if where else []
        matching = [r for r in self.rows if all(all((r.get('metadata') or {}).get(key) == value for key, value in clause.items()) for clause in clauses)]
        matching = sorted(matching, key=lambda r: r['distance'])[:n_results]
        return {'ids': [[r['id'] for r in matching]], 'documents': [[r['text'] for r in matching]], 'distances': [[r['distance'] for r in matching]], 'metadatas': [[deepcopy(r.get('metadata')) for r in matching]]}


def row(identity='chunk_0', text='PCA preserves variance.', distance=0.2, metadata=None):
    return dict(id=identity, text=text, distance=distance, metadata=metadata)


def managed(identity='material-A', **values):
    return dict(material_id=identity, source='lecture.pdf', course='C', semester='S', subject='ML', unit='U', **values)
