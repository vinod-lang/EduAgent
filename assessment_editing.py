"""Explicit professor edits preserve server-owned slots, evidence and target totals."""
from dataclasses import replace
import json
from assessment_spec import AssessmentError
from assessment_studio import validate_output

def edit_assessment(result, edits, *, pyq_text=''):
    if not isinstance(edits,list) or len(edits)!=len(result.questions):
        raise AssessmentError('Question count must match the current assessment.')
    fields={'question_text','marks','options','correct_answer','model_answer'}
    rows=[];marks=[]
    for question,edit in zip(result.questions,edits):
        if not isinstance(edit,dict) or set(edit)!=fields:raise AssessmentError('Only explicit question fields may be edited.')
        rows.append(dict(question_number=question.question_number,question_type=question.question_type,
            difficulty=question.difficulty,bloom_level=question.bloom_level,
            evidence_ids=list(question.evidence_ids),**edit))
        marks.append(edit['marks'])
    updated=validate_output(json.dumps({'questions':rows},ensure_ascii=False),result.spec,result.evidence,
                            pyq_text=pyq_text,professor_marks=tuple(marks))
    provenance=replace(result.provenance,professor_edited=True) if result.provenance is not None else None
    return replace(updated,provenance=provenance)

def current_edits(result):
    return [dict(question_text=q.question_text,marks=q.marks,options=dict(q.options),correct_answer=q.correct_answer,model_answer=q.model_answer) for q in result.questions]
