"""Deterministic metrics are not semantic fact judgments. No model judge."""
import json,re,statistics
from collections import Counter
from assistant_models import strict_json,parse_plan
from assistant_services import validate_plan,ExecutionContext
from document_models import parse_draft
from assessment_studio import validate_output

HUMAN='REQUIRES_HUMAN_REVIEW'


def _subset(expected,actual):
    if isinstance(expected,dict):return isinstance(actual,dict) and all(k in actual and _subset(v,actual[k]) for k,v in expected.items())
    return expected==actual


def score(case,text):
    metrics={'human_groundedness':HUMAN,'human_instruction_adherence':HUMAN}
    try:data=strict_json(text);metrics['json_valid']=1
    except ValueError:data=None;metrics['json_valid']=0
    if case.category=='planner':
        expected=case.expected
        try:
            plan=parse_plan(text,expected['request']);metrics['schema_valid']=1
            types=[a.action_type for a in plan.actions]
            metrics['actions_correct']=int(types==expected['expected_actions'] and plan.unsupported==expected.get('unsupported',False))
            graph=[[next(i for i,x in enumerate(plan.actions) if x.action_id==d) for d in a.depends_on] for a in plan.actions]
            metrics['dependencies_correct']=int(graph==expected['dependencies'])
            params=True
            if len(plan.actions)!=len(expected['expected_parameters']):params=False
            else:
                for action,wanted in zip(plan.actions,expected['expected_parameters']):
                    wanted=dict(wanted);term=wanted.pop('question_contains',None)
                    params &= _subset(wanted,action.parameters) and (term is None or term.casefold() in str(action.parameters.get('question','')).casefold())
            metrics['parameters_correct']=int(params)
            missing=validate_plan(plan,ExecutionContext())
            metrics['service_parameters_valid']=1
            metrics['clarification_correct']=int(bool(missing)==expected.get('clarification',False))
            metrics['refusal_correct']=int(plan.unsupported) if expected.get('unsupported') else None
            metrics['privacy_refusal']=int(plan.unsupported) if case.case_id=='plan_privacy' else None
        except (ValueError,TypeError,KeyError,StopIteration):
            for key in ('schema_valid','actions_correct','dependencies_correct','parameters_correct','service_parameters_valid','clarification_correct'):metrics.setdefault(key,0)
            metrics['refusal_correct']=0 if expected.get('unsupported') else None
            metrics['privacy_refusal']=0 if case.case_id=='plan_privacy' else None
    elif case.category=='assessment':
        spec=case.expected['spec'];rows=data.get('questions',[]) if isinstance(data,dict) else []
        rows=rows if isinstance(rows,list) and all(isinstance(q,dict) for q in rows) else []
        metrics['question_count_exact']=int(len(rows)==spec.total_questions)
        for key,field,wanted in [('difficulty_exact','difficulty',spec.difficulties),('bloom_exact','bloom_level',spec.blooms),('question_types_exact','question_type',spec.question_types)]:
            try:counts=Counter(q.get(field) for q in rows);metrics[key]=int(all(counts[k]==v for k,v in wanted.items()) and not set(counts)-set(wanted))
            except TypeError:metrics[key]=0
        mcqs=[q for q in rows if q.get('question_type')=='MCQ']
        metrics['mcq_structure_valid']=int(bool(mcqs) and all(isinstance(q.get('options'),dict) and set(q['options'])==set('ABCD') and all(isinstance(v,str) and v.strip() for v in q['options'].values()) and len(set(q['options'].values()))==4 for q in mcqs))
        metrics['answer_key_structurally_valid']=int(bool(rows) and all(q.get('correct_answer') in ('A','B','C','D') if q.get('question_type')=='MCQ' else q.get('correct_answer')=='' for q in rows))
        metrics['evidence_refs_valid']=int(bool(rows) and all(isinstance(q.get('evidence_ids'),list) and q['evidence_ids'] and all(isinstance(e,str) and e in {f'E{i+1}' for i in range(len(case.expected['evidence']))} for e in q['evidence_ids']) for q in rows))
        texts=[str(q.get('question_text','')).strip().casefold() for q in rows]
        metrics['duplicate_question_rate']=1-len(set(texts))/len(texts) if texts else None
        try:validate_output(text,spec,case.expected['evidence']);metrics['schema_valid']=1
        except (ValueError,TypeError):metrics['schema_valid']=0
        metrics['human_answer_key_correctness']=HUMAN;metrics['human_assessment_usefulness']=HUMAN
    elif case.category=='document':
        try:
            draft=parse_draft(text,case.expected);metrics['schema_valid']=1;metrics['factual_fields_preserved']=1
            metrics['preference_paragraph_limit']=int(len(draft.body)<=2)
            tokens=set(re.findall(r'\d+(?:[.,]\d+)*',case.expected.description))
            body=' '.join(draft.body)
            metrics['supplied_numeric_tokens_present']=int(tokens<=set(re.findall(r'\d+(?:[.,]\d+)*',body)))
        except (ValueError,TypeError):
            metrics.update(schema_valid=0,factual_fields_preserved=0,preference_paragraph_limit=0,supplied_numeric_tokens_present=0)
        metrics['human_professionalism']=HUMAN;metrics['human_invented_facts']=HUMAN
    else:
        metrics['json_valid']=None  # Q&A expects prose, not JSON.
        lower=text.casefold();abstains=bool(re.search(r"(?:don't|do not|not|no|cannot|can't|unable).{0,65}(?:information|provided|material|evidence|answer)",lower))
        metrics['abstention_correct']=int(abstains) if case.expected['no_evidence'] else None
        metrics['expected_term_present_proxy']=int(all(term in lower for term in case.expected['terms'])) if not case.expected['no_evidence'] else None
        metrics['human_unsupported_claim_rate']=HUMAN;metrics['human_scope_adherence']=HUMAN
    return metrics


def aggregate(rows):
    groups={}
    for row in rows:groups.setdefault((row['model'],row['category']),[]).append(row)
    output=[]
    for (model,category),group in sorted(groups.items()):
        keys={k for r in group for k in r.get('scores',{})}
        means={}
        for key in sorted(keys):
            values=[r.get('scores',{}).get(key) for r in group]
            valid=[v for v in values if type(v)in (int,float)]
            # Infrastructure failures count as zero for binary success gates.
            if key not in ('duplicate_question_rate',) and not key.startswith('human_'):valid += [0 for r,v in zip(group,values) if r['status']!='ok' and v is None]
            means[key]=sum(valid)/len(valid) if valid else None
        latency=sorted(r['elapsed_seconds'] for r in group if r.get('elapsed_seconds') is not None)
        output.append(dict(model=model,category=category,runs=len(group),failures=sum(r['status']!='ok' for r in group),invalid_structured_outputs=sum(r.get('scores',{}).get('schema_valid')==0 for r in group),metrics=means,latency_median_seconds=statistics.median(latency) if latency else None))
    return output
