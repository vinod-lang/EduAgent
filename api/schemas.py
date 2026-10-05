"""Explicit v1 transport models; domain validation remains the final authority."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
class Transport(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)
class DevLogin(Transport):identity:str=Field(min_length=1,max_length=100)
class Hierarchy(Transport):
    course:str=Field(min_length=1,max_length=200)
    semester:str=Field(min_length=1,max_length=200)
    subject:str=Field(min_length=1,max_length=200)
    unit:str=Field(min_length=1,max_length=200)
class Knowledge(Transport):
    question:str=Field(min_length=1,max_length=4000)
    filters:dict[str,str]=Field(default_factory=dict)
    final_k:int|None=Field(default=None,ge=1,le=20)
class AssessmentRequest(Transport):
    assessment_type:Literal['Quiz','Question Paper']
    course:str;semester:str;subject:str
    units:list[str]=Field(min_length=1,max_length=64)
    material_ids:list[str]=Field(default_factory=list,max_length=64)
    question_types:dict[str,int];difficulties:dict[str,int];blooms:dict[str,int]
    total_questions:int=Field(ge=1,le=100);total_marks:int=Field(ge=1,le=10000)
    title:str='Academic Assessment';institution:str='';instructions:str='Answer all questions.';topic:str='Key concepts and applications'
    pyq_handle:str|None=None
class DocumentRequest(Transport):
    document_type:str;description:str=Field(min_length=1,max_length=20000)
    tone:str='Formal & Natural';template_id:str='standard_academic'
    recipient:str='';sender:str='';title:str='';date:str='';reference_number:str='';subject:str='';signature:str='';additional_context:str=''
class DocumentEdit(Transport):
    title:str='';recipient:str='';sender:str='';date:str='';reference_number:str='';subject:str='';salutation:str='';body:list[str];closing:str='';signature:str=''
class Refine(Transport):instruction:str=Field(min_length=1,max_length=4000)
class Save(Transport):status:Literal['Draft','Final']='Draft'
class Restore(Transport):index:int=Field(ge=0)
class Fact(Transport):
    operation:Literal['add','update','remove']
    field:str='body';value:str='';fact_id:str|None=None
class Feedback(Transport):rating:Literal['Good','Needs Changes'];note:str=Field(default='',max_length=2000)
class Preference(Transport):
    instruction:str=Field(min_length=1,max_length=2000)
    category:str='tone_style';scope:str='document_type';document_type:str|None=None;template_id:str|None=None;tone:str|None=None
class AssessmentColumn(Transport):column:str;name:str;scale:str='percentage';maximum:float|None=None
class StudentMapping(Transport):
    sheet:str;header_row:int=Field(ge=1)
    student_id:str|None=None;student_name:str|None=None;attendance:str
    assessments:list[AssessmentColumn]=Field(min_length=1)
    attendance_scale:str='auto';assessment_number:str|None=None
class Analyze(Transport):view:str='All';search:str=Field(default='',max_length=200);marks_threshold:float=Field(default=50,ge=0);attendance_threshold:float=Field(default=70,ge=0,le=100)
class PlanRequest(Transport):request:str=Field(min_length=1,max_length=4000);student_handle:str|None=None
class Execute(Transport):confirmed:bool;retry:bool=False
class Profile(Transport):professor_id:str;display_name:str;institution_id:str;department_id:str
class Handle(Transport):handle:str
class StatusResponse(Transport):status:str
class MaterialResponse(Hierarchy):material_id:str;filename:str;created_at:str
class MaterialDetailResponse(MaterialResponse):visibility:Literal['PRIVATE','COURSE','DEPARTMENT','INSTITUTE'];can_manage:bool
class Source(Transport):source:str;material_id:str|None=None
class Answer(Transport):answer:str;grounded:bool;sources:list[Source]

# Explicit response contracts keep internal provenance/facts out of generic responses.
class LoginResponse(Transport):status:str;authentication:str;csrf_token:str
class CSRFResponse(Transport):csrf_token:str
class ReadinessResponse(Transport):status:str;authentication:str;storage_probe:str;production_ready:bool
class AIStatus(Transport):
    provider:str;preferred_model:str;effective_model:str|None;fallback_active:bool|None
    embedding:str;candidate_k:int;final_k:int;threshold:float;reranker:bool;router:bool
class UploadResponse(Transport):success:bool;duplicate:bool;material:MaterialResponse|None;message:str
class MaterialUpdateResponse(Transport):status:str;success:bool
class DeletionResponse(Transport):success:bool;sqlite_deleted:bool|None;vectors_deleted:int|None;file_deleted:bool|None
class RetrievalResponse(Transport):status:str;sources:list[Source];evidence_count:int
class DocumentResponse(DocumentEdit):handle:str;document_id:str|None;document_type:str;version_count:int
class VersionResponse(Transport):version_id:str;version_number:int;source:str;created_at:str
class FactResponse(Transport):fact_id:str;field:str;value:str;source:str
class QuestionResponse(Transport):
    question_number:int;question_type:str;question_text:str;options:dict[str,str]
    correct_answer:str;model_answer:str;difficulty:str;bloom_level:str;marks:int
class AssessmentResponse(Transport):handle:str;title:str;assessment_type:str;total_marks:int;questions:list[QuestionResponse];revision:int;professor_edited:bool;validation:dict[str,bool]
class AssessmentQuestionEdit(Transport):
    question_text:str=Field(min_length=1,max_length=6000)
    marks:int=Field(ge=1,le=10000)
    options:dict[str,str]
    correct_answer:str=Field(max_length=1)
    model_answer:str=Field(min_length=1,max_length=6000)
class AssessmentEdit(Transport):revision:int=Field(ge=0);questions:list[AssessmentQuestionEdit]=Field(min_length=1,max_length=100)
class PreferenceResponse(Transport):preference_id:str;instruction:str;category:str;scope:str;active:bool
class DraftMetadata(Transport):document_id:str;template_id:str;created_at:str;updated_at:str;status:str
class BookResponse(Handle):sheets:list[str]
class StudentResponse(Transport):students:list[dict];summary:dict
class ActionResponse(Transport):action_id:str;action_type:str;parameters:dict;depends_on:list[str]
class PlanResponse(Handle):unsupported:bool;actions:list[ActionResponse]
class ClarificationResponse(Transport):action_id:str;missing_fields:list[str]
class PreviewResponse(PlanResponse):valid:bool;clarifications:list[ClarificationResponse]
class ActionOutcome(Transport):action_id:str;status:str;type:str;summary:str
class ExecutionResponse(Transport):status:str;results:list[ActionOutcome]
class ActivityResponse(Transport):actor_professor_id:str;action:str;timestamp:str
class DashboardResponse(Transport):material_count:int;courses:list[str];materials:list[MaterialResponse];saved_drafts:list[DraftMetadata];activity:list[ActivityResponse]

class ResolveEdit(Transport):
    draft:DocumentEdit
    update_confirmed:bool
    replacements:dict[str,str]=Field(default_factory=dict)
class PreferenceUpdate(Transport):instruction:str|None=None;active:bool|None=None
