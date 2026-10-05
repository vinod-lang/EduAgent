"""Request-local SQLite selection; presentation adapters never execute SQL."""
from contextlib import contextmanager

@contextmanager
def storage_context(path):
    import db
    with db.storage_context(path):yield

def initialize_development_storage(path):
    """Explicit offline bootstrap, never called from imports or API requests."""
    import db
    from document_repository import init_document_schema
    with storage_context(path):
        db.init_db()
        with db.material_connection() as conn:init_document_schema(conn)

class ConfiguredVectors:
    """Lazy explicit vector path; isolated API storage never falls back to Streamlit."""
    def __init__(self,path):self.path=path
    def collection(self):
        from vector_store import get_collection
        return get_collection(self.path)
    def add_material_chunks(self,ids,chunks,metadata):self.collection().add(ids=ids,documents=chunks,metadatas=[dict(metadata) for _ in chunks])
    def get_material_chunks(self,ids):return self.collection().get(ids=ids)
    def delete_material_chunks(self,ids):
        if ids:self.collection().delete(ids=ids)
    def update_material_chunks(self,ids,metadata):
        if ids:self.collection().update(ids=ids,metadatas=metadata)
