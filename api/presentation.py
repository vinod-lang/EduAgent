"""Allowlisted response projection; never recursively serialize domain internals."""
def profile(p):return dict(professor_id=p.professor_id,display_name=p.display_name,institution_id=p.institution_id,department_id=p.department_id)
def material(m):return dict(material_id=m['material_id'],filename=m['original_filename'],course=m['course'],semester=m['semester'],subject=m['subject'],unit=m['unit'],created_at=m['created_at'])
def sources(result):return [dict(source=s.source,material_id=s.material_id) for s in result.sources]
def document(workspace,handle):
 d=workspace.versions.current
 return dict(handle=handle,document_id=workspace.document_id,document_type=d.document_type,
 saved=workspace.saved_version_id==workspace.versions.version_ids[-1],status=workspace.saved_status,
 versions=[dict(version_number=i+1,source=workspace.versions.sources[i],created_at=workspace.versions.timestamps[i]) for i in range(len(workspace.versions.history))],
 facts=[dict(fact_id=f.fact_id,field=f.field,value=f.value,source=f.source) for f in workspace.versions.expectation_snapshots[-1]],
 provenance=provenance(workspace.versions.provenance_snapshots[-1]),**{k:list(getattr(d,k)) if k=='body' else getattr(d,k) for k in ('title','recipient','sender','date','reference_number','subject','salutation','body','closing','signature')},version_count=len(workspace.versions.history))
def assessment(workspace,handle):
 a=workspace.result
 return {'revision':workspace.revision,'professor_edited':workspace.revision>0,'validation':dict(structure=True,marks=True,distributions=True,evidence_references=True,answer_key=True),'handle':handle,'title':a.spec.title,'assessment_type':a.spec.assessment_type,'total_marks':a.spec.total_marks,'questions':[dict(question_number=q.question_number,question_type=q.question_type,question_text=q.question_text,options=dict(q.options),correct_answer=q.correct_answer,model_answer=q.model_answer,difficulty=q.difficulty,bloom_level=q.bloom_level,marks=q.marks) for q in a.questions]}
def plan(plan,handle):return {'handle':handle,'unsupported':plan.unsupported,'actions':[dict(action_id=a.action_id,action_type=a.action_type,parameters=a.parameters,depends_on=list(a.depends_on)) for a in plan.actions]}
def execution(report):
 # Action payloads stay server-side; dedicated feature endpoints deliver typed artifacts.
 return {'status':report.status,'results':[{'action_id':a.action_id,'status':a.status,'type':a.result_type,'summary':a.safe_summary} for a in report.results]}


def provenance(value):
 if value is None:return None
 return {k:getattr(value,k) for k in ('generation_type','generated_at','validation_status','attempts_used','model','provider','grounded','professor_edited','preferences_applied')}
