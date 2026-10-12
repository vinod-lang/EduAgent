"""Server-only aggregate indexing diagnostics; never serialize content or paths."""
from contextlib import contextmanager
from contextvars import ContextVar
import json,logging,time
from pathlib import Path
_STATE=ContextVar('indexing_diagnostics',default=None)
LOGGER=logging.getLogger('eduagent.indexing')
COUNTS={'extracted_characters','chunk_count','maximum_batch_size','attempted_batch_size','inserted_batches','selected_batch_size'}
BOOLEANS={'success','failed','rollback_attempted','rollback_failed'}
STAGES={'extraction','chunking','collision_check','embedding_initialization','storage_initialization','vector_insertion','verification','registration'}
CATEGORIES={'batch_size_rejection','storage_initialization_failure','vector_insertion_failure','verification_failure','embedding_failure','registry_failure','extraction_failure','storage_failure'}
def path_category(path):
    parts=Path(path).parts
    return 'development_runtime' if '.runtime' in parts else 'legacy_storage' if Path(path).name=='chroma_db' else 'configured_storage'
def observe(**values):
    state=_STATE.get()
    if state is None:return
    for key,value in values.items():
        if key in COUNTS and type(value) is int and value>=0:state[key]=value
        elif key in BOOLEANS and type(value) is bool:state[key]=value
        elif key=='indexing_stage' and value in STAGES:state[key]=value
        elif key=='failure_category' and value in CATEGORIES:state[key]=value
        elif key in ('embedding_initialization','vector_rollback','file_rollback') and value in ('started','pass','fail'):state[key]=value
        elif key=='storage_path_category' and value in ('development_runtime','legacy_storage','configured_storage'):state[key]=value
        elif key in ('exception_type','rollback_exception_type'):
            import re
            if isinstance(value,str) and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,79}',value):state[key]=value
@contextmanager
def diagnostic_scope():
    state={'inserted_batches':0,'rollback_attempted':False,'embedding_initialization':'not_requested'}
    token=_STATE.set(state);started=time.perf_counter()
    try:yield
    except Exception as exc:
        observe(failed=True,exception_type=type(exc).__name__)
        raise
    finally:
        if state.get('failed') and 'failure_category' not in state:
            state['failure_category']={'verification':'verification_failure','registration':'registry_failure','extraction':'extraction_failure','collision_check':'storage_initialization_failure'}.get(state.get('indexing_stage'),'storage_failure')
        state['duration_seconds']=round(time.perf_counter()-started,3)
        LOGGER.warning('MATERIAL_INDEX %s',json.dumps(state,sort_keys=True)) if state.get('failed') else LOGGER.info('MATERIAL_INDEX %s',json.dumps(state,sort_keys=True))
        _STATE.reset(token)


@contextmanager
def development_logging(enabled):
    """Dedicated terminal sink during development lifespan, no root changes."""
    if not enabled:
        yield
        return
    # Nested lifespan/configuration must not install a second terminal sink.
    if any(getattr(handler,'_eduagent_indexing_sink',False) for handler in LOGGER.handlers):
        yield
        return
    previous=(LOGGER.level,LOGGER.propagate,LOGGER.disabled)
    handler=logging.StreamHandler()
    handler._eduagent_indexing_sink=True
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate=False
    LOGGER.disabled=False
    try:yield
    finally:
        LOGGER.removeHandler(handler)
        handler.close()
        LOGGER.setLevel(previous[0])
        LOGGER.propagate=previous[1]
        LOGGER.disabled=previous[2]
