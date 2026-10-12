"""Bounded Chroma document calls also bound each embedding encode invocation."""
from config import get_index_batch_size
from indexing_diagnostics import observe

def insert_chunks(collection,ids,chunks,metadata):
    if len(ids)!=len(chunks) or len(set(ids))!=len(ids):raise ValueError('Invalid exact chunk IDs.')
    requested=get_index_batch_size()
    from inspect import getattr_static
    client=getattr_static(collection,'_client',None)
    getter=getattr(client,'get_max_batch_size',None)
    try:maximum=getter() if callable(getter) else None
    except Exception:
        observe(failure_category='storage_initialization_failure')
        raise
    if maximum is not None and (type(maximum) is not int or maximum<1):raise ValueError('Invalid vector batch capability.')
    # Stay below the reported boundary where possible; a one-record limit is usable.
    size=min(requested,max(1,maximum-1)) if maximum is not None else min(requested,100)
    if maximum is not None:observe(maximum_batch_size=maximum)
    observe(selected_batch_size=size,indexing_stage='vector_insertion')
    completed=0
    for start in range(0,len(ids),size):
        batch_ids=ids[start:start+size];documents=chunks[start:start+size]
        observe(attempted_batch_size=len(batch_ids))
        try:collection.add(ids=batch_ids,documents=documents,metadatas=[dict(metadata) for _ in batch_ids])
        except Exception as exc:
            # Recognize only the known Chroma batch error; never log its message.
            message=str(exc).lower()
            category='batch_size_rejection' if 'batch size' in message and ('max' in message or 'exceed' in message) else 'vector_insertion_failure'
            observe(failure_category=category,exception_type=type(exc).__name__)
            raise
        completed+=1;observe(inserted_batches=completed)
    return completed
