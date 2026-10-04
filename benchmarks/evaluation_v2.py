"""Explicit V2 live evaluation, controlled schemas and separate facts; no repair loops."""
import argparse,json,time,csv,math,re,statistics,hashlib,copy
from pathlib import Path
from collections import Counter
from dataclasses import asdict
from datetime import datetime,timezone
import ai_provider
from .cases_v2 import cases_v2,load_v2
from .contracts_v2 import response_schema,strict_contract_schema
from .failures_v2 import categorize
from .scoring import score,HUMAN

MODES=('prompt_only','schema_constrained','strict_contract')

def facts(case,text):
    if case.category!='document':return {}
    body_available=False;paragraphs=None;body=text if isinstance(text,str) else ''
    try:
        from assistant_models import strict_json
        data=strict_json(text)
        paragraphs=data['body']
        if not isinstance(paragraphs,list) or not paragraphs or not all(isinstance(p,str) for p in paragraphs):raise ValueError()
        body=' '.join(paragraphs);body_available=True
    except (ValueError,TypeError,KeyError):pass
    wanted=case.expected;number=lambda t:set(re.findall(r'\d+(?:[.,]\d+)*',t))
    retained=int(number(wanted.description)<=number(body))
    dates=int(not wanted.date or wanted.date.casefold() in body.casefold())
    refs=int(not wanted.reference_number or wanted.reference_number in body)
    names=int(not wanted.recipient or wanted.recipient.casefold() in body.casefold())
    extra=len(number(body)-number(wanted.description+' '+wanted.date+' '+wanted.reference_number))
    return dict(structured_body_available=int(body_available),numeric_facts_retained=retained,dates_retained=dates,references_retained=refs,named_entities_retained=names,unsupported_numeric_count=extra,facts_complete=int(body_available and retained and dates and refs and names and extra==0),preference_followed=int(len(paragraphs)<=2) if body_available else None)


def evaluate(case,text):
    result=score(case,text);result.update(facts(case,text))
    if case.category=='assessment' and case.expected['spec'].question_types['MCQ']==0:
        result['mcq_structure_valid']=None
    if case.category=='planner':
        result['policy_valid']=result['actions_correct'] if case.expected.get('unsupported') else None
        result['exact_plan_success']=int(all(result.get(k)==1 for k in ('schema_valid','actions_correct','parameters_correct','dependencies_correct','clarification_correct','service_parameters_valid')))
    return result

def percentile95(values):
    return sorted(values)[math.ceil(.95*len(values))-1] if len(values)>=20 else None

def summarize(rows):
    out=[]
    for model,mode,task in sorted({(x['model'],x['mode'],x['task']) for x in rows}):
        group=[x for x in rows if (x['model'],x['mode'],x['task'])==(model,mode,task)]
        keys={k for x in group for k,v in x['metrics'].items() if type(v)in (int,float)}
        counts={}
        for key in sorted(keys):
            applicable=[x for x in group if x['metrics'].get(key) is not None]
            counts[key]=dict(sum=sum(x['metrics'][key] for x in applicable),attempts=len(applicable))
        latency=[x['latency_seconds'] for x in group if x['latency_seconds'] is not None]
        out.append(dict(model=model,mode=mode,task=task,attempts=len(group),provider_failures=sum(x['status']!='ok' for x in group),metrics=counts,median_seconds=statistics.median(latency) if latency else None,p95_seconds=percentile95(latency),failure_categories=dict(Counter(c for x in group for c in x['failure_categories']))))
    return out

def decision(groups):
    requirements={'planner_schema':.95,'planner_exact':.90,'refusal_privacy':1.0,'document_schema':.95,'document_required_facts':.95,'assessment_contract':.95,'minimum_distinct_cases_per_task':20,'retrieval_hit1_gain':.05,'retrieval_no_evidence_fpr_max':.05,'human_review':'PENDING HUMAN REVIEW'}
    checks=[]
    for group in groups:
        keys={'planner':{'schema_valid':.95,'exact_plan_success':.90,'policy_valid':1.0},'assessment':{'schema_valid':.95},'document':{'schema_valid':.95,'facts_complete':.95},'qa':{}}[group['task']]
        reasons=[]
        if group['attempts']<20:reasons.append('Insufficient category coverage.')
        if group['provider_failures']:reasons.append('Provider failure recorded.')
        for key,target in keys.items():
            value=group['metrics'].get(key)
            if not value or not value['attempts'] or value['sum']/value['attempts']<target:reasons.append(key+' below gate or unavailable.')
        checks.append(dict(model=group['model'],mode=group['mode'],task=group['task'],deterministic_pass=not reasons,reasons=reasons))
    return dict(outcome='F',description='More human review required before any production change.',production_change=False,requirements=requirements,checks=checks)


def write_review(rows,directory):
    directory=Path(directory)
    with (directory/'human_review.csv').open('w',newline='') as f:
        fields=['case_id','model','mode','task','prompt_summary','expected_facts','output_reference','correctness_0_2','groundedness_0_2','usefulness_0_2','professionalism_0_2','hallucination_flag','reviewer_notes','review_status']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for i,row in enumerate(rows):writer.writerow({k:row.get(k,'') for k in fields[:6]}|{'output_reference':f'results.json rows[{i}]','review_status':'PENDING HUMAN REVIEW'})

def run(models,modes,output,*,call=None,selected=None):
    if set(models)-{'llama3.2:3b','qwen3.5:0.8b','qwen3:1.7b'} or set(modes)-set(MODES):raise ValueError('Reviewed models/modes only.')
    root=Path(__file__).resolve().parents[1];output=Path(output).resolve()
    if output.is_relative_to(root) and not output.is_relative_to(root/'benchmarks'/'results'):raise ValueError('Isolated outputs only.')
    output.mkdir(parents=True,exist_ok=True);call=call or ai_provider.generate_chat_measured;rows=[];cases=selected or cases_v2()
    for model in models:
        for mode in modes:
            for case in cases:
                config=dict(temperature=0,seed=17,num_ctx=4096,num_predict=2048)
                row=dict(case_id=case.case_id,model=model,mode=mode,task=case.category,status='ok',metrics={},failure_categories=[],prompt_summary=case.messages[-1]['content'][:400],expected_facts=case.expected.description if case.category=='document' else 'Synthetic expected contract; see versioned fixture.',latency_seconds=None)
                start=time.perf_counter()
                try:
                    measurement=call(list(case.messages),model=model,options=config,think=False,timeout_seconds=90,response_format=strict_contract_schema(case) if mode=='strict_contract' else response_schema(case) if mode=='schema_constrained' else None)
                    row.update(measurement=asdict(measurement),latency_seconds=measurement.elapsed_seconds,metrics=evaluate(case,measurement.text),failure_categories=categorize(case,measurement.text,output_tokens=measurement.output_tokens,token_limit=2048) if case.structured else [])
                    if case.category=='document' and (any(row['metrics'].get(k)==0 for k in ('numeric_facts_retained','dates_retained','references_retained','named_entities_retained')) or row['metrics'].get('unsupported_numeric_count',0)>0):row['failure_categories']=sorted(set(row['failure_categories'])|{'factual_preservation_violation'})
                except ai_provider.AIProviderError as exc:
                    row.update(status='timeout' if exc.__cause__ is not None and (isinstance(exc.__cause__,TimeoutError) or 'Timeout' in type(exc.__cause__).__name__) else 'unavailable' if getattr(exc.__cause__,'status_code',None)==404 else 'provider_error',error=type(exc).__name__,failure_categories=['other'],latency_seconds=time.perf_counter()-start)
                    # Failed generation remains in critical success denominators.
                    row['metrics']=evaluate(case,'')
                rows.append(row);(output/'progress.json').write_text(json.dumps(rows,indent=2))
                print(model,mode,case.case_id,row['status'],row['metrics'].get('schema_valid'),round(row['latency_seconds'],2),flush=True)
    result=dict(version='evaluation-v2',fixture_version=load_v2()['version'],utc=datetime.now(timezone.utc).isoformat(),protocol=dict(options=config,repeats=1,timeout_seconds=90,repair_attempts=0,production_modes_unchanged=True),rows=rows,summary=summarize(rows))
    result['decision']=decision(result['summary']);(output/'results.json').write_text(json.dumps(result,indent=2));write_review(rows,output)
    return result

def finalize_existing(progress_path,output):
    """Offline recovery only: preserve raw evidence, derive current metrics, never generate."""
    root=Path(__file__).resolve().parents[1];source=Path(progress_path).resolve();output=Path(output).resolve()
    for path in (source,output):
        if path.is_relative_to(root) and not path.is_relative_to(root/'benchmarks'/'results'):raise ValueError('Use isolated benchmark artifacts only.')
    original=source.read_bytes()
    if len(original)>20_000_000:raise ValueError('Progress artifact too large.')
    rows=json.loads(original)
    if not isinstance(rows,list) or not rows:raise ValueError('No completed benchmark rows.')
    cases={c.case_id:c for c in cases_v2()};derived=[];seen=set()
    for original_row in rows:
        row=copy.deepcopy(original_row);key=(row['model'],row['mode'],row['case_id'])
        if key in seen or row['case_id'] not in cases:raise ValueError('Unknown or duplicate completed case.')
        seen.add(key);case=cases[row['case_id']]
        row['original_metrics']=row['metrics']
        if case.category=='planner':row['expected_facts']=json.dumps({k:v for k,v in case.expected.items() if k!='request'},sort_keys=True)
        elif case.category=='assessment':row['expected_facts']=json.dumps({'slots':[slot.to_dict() for slot in case.expected['spec'].plan],'valid_evidence_ids':[f'E{i+1}' for i in range(len(case.expected['evidence']))]})
        elif case.category=='qa':row['expected_facts']=json.dumps(case.expected,sort_keys=True)
        raw=row.get('measurement',{}).get('text','')
        row['metrics']=evaluate(case,raw)
        labels=categorize(case,raw,output_tokens=row.get('measurement',{}).get('output_tokens'),token_limit=2048) if case.structured else []
        if case.category=='planner':
            for metric,label in [('parameters_correct','invalid_planner_parameters'),('dependencies_correct','invalid_dependency'),('clarification_correct','clarification_failure')]:
                if row['metrics'].get('schema_valid')==1 and row['metrics'].get(metric)==0:labels.append(label)
            if case.expected.get('unsupported') and row['metrics'].get('actions_correct')==0:labels.append('policy_refusal_failure')
            elif row['metrics'].get('schema_valid')==1 and row['metrics'].get('actions_correct')==0:labels.append('wrong_action_selection')
            row['metrics']['privacy_policy_valid']=row['metrics']['actions_correct'] if case.expected.get('privacy') else None
        if case.category=='document' and (any(row['metrics'].get(k)==0 for k in ('numeric_facts_retained','dates_retained','references_retained','named_entities_retained')) or row['metrics'].get('unsupported_numeric_count',0)>0):labels.append('factual_preservation_violation')
        row['failure_categories']=sorted(set(labels));derived.append(row)
    result=dict(version='evaluation-v2-offline-recovery',fixture_version='synthetic-v2',utc=datetime.now(timezone.utc).isoformat(),source_progress_sha256=hashlib.sha256(original).hexdigest(),additional_live_calls=0,completed_rows=len(derived),interrupted=True,rows=derived,summary=summarize(derived),notes=['Raw responses and recorded latency unchanged; original metrics retained.','Student-filter expected clarification corrected for absent dataset.','Exact-plan scoring requires valid service parameters.','Incomplete/unrun matrix cells are NOT RERUN FOR RESOURCE SAFETY.','One in-flight generation was interrupted; no response exists, so it is not scored.','Strict-contract and supplementary cases have mock tests only, not live results.','Fact checks use structured body when available, otherwise raw text; raw-text success never qualifies an unusable document.','MCQ metrics exclude descriptive-only scenarios as not applicable.'])
    result['decision']=decision(result['summary']);output.mkdir(parents=True,exist_ok=True)
    (output/'results.json').write_text(json.dumps(result,indent=2));write_review(derived,output)
    with (output/'metrics.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['model','mode','task','attempts','metric','sum','applicable_count','median_seconds','p95_seconds'])
        for g in result['summary']:
            for key,value in g['metrics'].items():writer.writerow([g['model'],g['mode'],g['task'],g['attempts'],key,value['sum'],value['attempts'],g['median_seconds'],g['p95_seconds']])
    assert source.read_bytes()==original
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',action='append',required=True);p.add_argument('--mode',action='append',choices=MODES,required=True);p.add_argument('--output',required=True);p.add_argument('--supplementary',action='store_true');p.add_argument('--contract-pilot',action='store_true');args=p.parse_args()
    from .cases_v2 import supplementary_cases
    run(args.model,args.mode,args.output,selected=[c for c in cases_v2() if c.case_id in ('v2_plan_0','v2_plan_13','v2_plan_24','v2_assessment_0','v2_assessment_1','v2_document_0','v2_document_6')] if args.contract_pilot else supplementary_cases() if args.supplementary else None)
if __name__=='__main__':main()
