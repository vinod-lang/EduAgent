"""Request-scoped terminal-only development tracing. Never retains model content."""
from contextlib import contextmanager
from contextvars import ContextVar
import re
import time

_ACTIVE=ContextVar('development_generation_trace',default=None)
FIELDS=frozenset('document_type title recipient sender date reference_number subject signature salutation closing body questions question_number question_type question_text model_answer options correct_answer difficulty bloom_level marks evidence_ids'.split())
RULES=frozenset('protected_fact_changed required_field_missing type const enum minItems maxItems uniqueItems oneOf minimum maximum minLength maxLength additionalProperties structured_output_invalid normalization_invalid provider_failure protected_body_fact_missing unsupported_location invented_approval unsupported_factual_value empty_body placeholder incomplete_sentence drafting_commentary product_validation schema_validation question_count marks_total slot_marks slot_distribution evidence_reference duplicate_question pyq_copy mcq_structure request_or_session_failure'.split())
STAGES=frozenset('provider_completed parse normalization schema quality fact_validation product_validation question_count_validation marks_validation difficulty_validation bloom_validation evidence_validation duplicate_validation session_result'.split())

class Trace:
 def __init__(self,kind,metadata):
  self.kind=kind;self.started=time.perf_counter();self.state={stage:'not_run' for stage in STAGES};self.failed=False
  from ai_provider import get_default_model_name
  self.emit(request_received=True,model=get_default_model_name(),**metadata)
 def emit(self,**metadata):
  safe={}
  for key,value in metadata.items():
   if key in STAGES and value in ('pass','fail','not_run','skipped',True,False):safe[key]=value
   elif key=='failure_field' and isinstance(value,str) and value in FIELDS:safe[key]=value
   elif key=='failure_rule' and isinstance(value,str) and value in RULES:safe[key]=value
   elif key=='generation_attempt' and type(value) is int and value in (1,2):safe[key]=value
   elif key=='reason' and value in ('placeholder','unsupported_factual_value'):safe[key]=value
   elif key=='corrective_retry' and value in ('started','pass','fail'):safe[key]=value
   elif key in ('failure_code','final_failure_code') and isinstance(value,str) and value in ('INVALID_JSON','SCHEMA_INVALID','PRODUCT_VALIDATION_FAILED','FACT_PRESERVATION_FAILED','DOCUMENT_QUALITY_FAILED','PROVIDER_ERROR','TIMEOUT','INSUFFICIENT_EVIDENCE','INVALID_REQUEST','SESSION_FAILURE','UNEXPECTED_FAILURE','NONE'):safe[key]=value
   elif key=='document_type':
    from document_models import CATALOG
    if isinstance(value,str) and value in CATALOG:safe[key]=value
   elif key=='model' and isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}',value):safe[key]=value
   elif key in ('request_received','completed') and type(value) is bool:safe[key]=value
   elif key in ('question_count','target_marks','expected','actual','question_number') and type(value) is int and 0<=value<=1000000:safe[key]=value
   elif key=='elapsed_seconds' and type(value) in (int,float) and 0<=value<=1000000:safe[key]=round(value,3)
  if safe:print('['+self.kind+'] '+' '.join(f'{k}={str(v).lower() if type(v) is bool else v}' for k,v in safe.items()),flush=True)
 def stage(self,stage,passed=True,**metadata):
  if stage not in STAGES:return
  self.state[stage]='pass' if passed else 'fail';self.failed=self.failed or not passed
  self.emit(**{stage:self.state[stage]},**metadata)

@contextmanager
def development_trace(enabled,kind,**metadata):
 if not enabled or kind not in ('DOC_GEN','ASSESSMENT_GEN'):
  yield;return
 trace=Trace(kind,metadata);token=_ACTIVE.set(trace)
 try:
  yield
 except Exception:
  if not trace.failed:trace.emit(failure_code='UNEXPECTED_FAILURE',failure_rule='request_or_session_failure')
  raise
 finally:
  trace.emit(**trace.state,elapsed_seconds=time.perf_counter()-trace.started)
  _ACTIVE.reset(token)

def stage(name,passed=True,**metadata):
 trace=_ACTIVE.get()
 if trace is not None:trace.stage(name,passed,**metadata)

def event(**metadata):
 trace=_ACTIVE.get()
 if trace is not None:trace.emit(**metadata)

def schema_failure(errors,fact_fields=()):
 if _ACTIVE.get() is None:return
 error=next((e for e in errors if e.path and e.path[0] in fact_fields),errors[0])
 path=list(error.path);field=next((p for p in reversed(path) if isinstance(p,str) and p in FIELDS),None)
 if error.validator=='required':field=next((k for k in error.validator_value if k not in error.instance and k in FIELDS),field)
 rule='protected_fact_changed' if field in fact_fields and error.validator=='const' else 'required_field_missing' if error.validator=='required' else error.validator
 meta=dict(failure_rule=rule,failure_field=field)
 # Log only integer counts/marks, never string values from documents/evidence.
 if field in ('marks','question_number') and error.validator=='const':meta.update(expected=error.validator_value,actual=error.instance)
 if field=='questions' and error.validator in ('minItems','maxItems'):meta.update(expected=error.validator_value,actual=len(error.instance))
 stage('schema',False,**meta)
 if field in fact_fields:stage('fact_validation',False,failure_rule=rule,failure_field=field)
 mapping={'marks':'marks_validation','difficulty':'difficulty_validation','bloom_level':'bloom_validation','evidence_ids':'evidence_validation','questions':'question_count_validation'}
 if field in mapping:stage(mapping[field],False,**meta)


def assessment_checks(data,spec,evidence):
 """Observations only: existing schema/product validators still decide acceptance."""
 if _ACTIVE.get() is None:return
 from assessment_studio import normalized
 questions=data.get('questions') if isinstance(data,dict) else None
 if not isinstance(questions,list):return
 stage('question_count_validation',len(questions)==spec.total_questions,failure_rule='question_count',expected=spec.total_questions,actual=len(questions))
 if not all(isinstance(q,dict) for q in questions):return
 marks=[q.get('marks') for q in questions];total=sum(marks) if all(type(m) is int and m>=0 for m in marks) else None
 stage('marks_validation',total==spec.total_marks,failure_rule='marks_total',expected=spec.total_marks,actual=total)
 for key,expected,name in (('difficulty',spec.difficulties,'difficulty_validation'),('bloom_level',spec.blooms,'bloom_validation')):
  okay=True
  for label,count in expected.items():
   actual=sum(q.get(key)==label for q in questions)
   if actual!=count:stage(name,False,failure_rule='slot_distribution',failure_field=key,expected=count,actual=actual);okay=False
  if okay:stage(name)
 for slot,q in zip(spec.plan,questions):
  for key,name in (('marks','marks_validation'),('difficulty','difficulty_validation'),('bloom_level','bloom_validation')):
   if q.get(key)!=getattr(slot,key):stage(name,False,failure_rule='slot_marks' if key=='marks' else 'slot_distribution',failure_field=key,question_number=slot.question_number)
 registry={f'E{i+1}' for i in range(len(evidence))}
 refs=[q.get('evidence_ids') for q in questions]
 valid=all(isinstance(v,list) and bool(v) and all(isinstance(ref,str) and ref in registry for ref in v) and len(set(v))==len(v) for v in refs)
 stage('evidence_validation',valid,failure_rule='evidence_reference')
 texts=[q.get('question_text') for q in questions]
 valid=all(isinstance(t,str) and bool(normalized(t)) for t in texts)
 if valid:valid=len({normalized(t) for t in texts})==len(texts)
 stage('duplicate_validation',valid,failure_rule='duplicate_question')


def provider_completed():
 if _ACTIVE.get() is None:return
 from ai_provider import get_last_generation_selection,get_default_model_name
 selection=get_last_generation_selection()
 event(model=selection.effective_model if selection else get_default_model_name())
 stage('provider_completed')
