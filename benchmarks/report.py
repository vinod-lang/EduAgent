"""Inspectable raw metrics and blank human review sheets; never fabricated scores."""
import csv,json
from pathlib import Path
from .scoring import aggregate,HUMAN

RUBRIC={'groundedness':'0 unsupported; 1 partially supported; 2 fully supported', 'professionalism':'0 unusable; 1 needs edits; 2 professional', 'instruction_adherence':'0 violates; 1 partial; 2 follows', 'assessment_usefulness':'0 unusable; 1 needs edits; 2 useful', 'unsupported_claim_rate':'Reviewer counts unsupported factual claims / all factual claims; blank if not judged'}


def gate(groups, *, minimum_runs=20):
    reasons=[]
    for category in ('planner','qa','assessment','document'):
        rows=[r for r in groups if r['category']==category]
        if len(rows)!=1 or rows[0]['runs']<minimum_runs:reasons.append(category+': insufficient coverage')
        if rows and rows[0]['failures']:reasons.append(category+': infrastructure failure')
        if rows:
            metrics=rows[0]['metrics']
            required={'planner':['schema_valid','actions_correct','parameters_correct','dependencies_correct','clarification_correct','privacy_refusal','refusal_correct'],'qa':['abstention_correct'],'assessment':['schema_valid'],'document':['schema_valid','factual_fields_preserved']}[category]
            for key in required:
                if metrics.get(key) is None or metrics[key]<.95:reasons.append(category+': '+key+' below 95%')
            if rows[0]['latency_median_seconds'] is None or rows[0]['latency_median_seconds']>30:reasons.append(category+': median latency exceeds 30 seconds or unknown')
    reasons.append('Subjective factual/quality review and resource headroom require professor review; not automatically approved.')
    return dict(recommendation='NO CHANGE RECOMMENDED YET',reasons=reasons,policy='At least 20 trials/category, deterministic critical gates >=95%, median <=30s, human factual/privacy review and memory headroom. Pilot protocol cannot satisfy full promotion coverage.')


def write_report(result,directory):
    directory=Path(directory).resolve()
    root=Path(__file__).resolve().parents[1]
    if directory.is_relative_to(root) and not directory.is_relative_to(root/'benchmarks'/'results'):
        raise ValueError('Benchmark output within the repository must use benchmarks/results, never runtime/source directories.')
    directory.mkdir(parents=True,exist_ok=True)
    groups=aggregate(result['runs'])
    report=dict(result,aggregates=groups,quality_gates={model:gate([g for g in groups if g['model']==model]) for model in sorted({g['model'] for g in groups})},human_review_rubric=RUBRIC)
    (directory/'results.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    with (directory/'metrics.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['model','category','runs','failures','median_seconds','metric','value'])
        for row in groups:
            for key,value in row['metrics'].items():writer.writerow([row['model'],row['category'],row['runs'],row['failures'],row['latency_median_seconds'],key,value])
    with (directory/'human_review.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['model','case','repeat','response_file','groundedness_0_2','professionalism_0_2','instruction_adherence_0_2','assessment_usefulness_0_2','unsupported_claim_count','total_claim_count','notes'])
        for r in result['runs']:writer.writerow([r['model'],r['case_id'],r['repeat'],'results.json','','','','','','',HUMAN])
    lines=['# EduAgent AI benchmark','', 'Pilot results; all subjective quality scores require human review. No automatic model recommendation.','', '| Model | Category | Trials | Provider failures | Invalid structured outputs | Median seconds |','|---|---|---:|---:|---:|---:|']
    for r in groups:lines.append(f"| {r['model']} | {r['category']} | {r['runs']} | {r['failures']} | {r['invalid_structured_outputs']} | {r['latency_median_seconds']} |")
    lines+=['','Promotion gates: '+next(iter(report['quality_gates'].values()),{'policy':'No live model evidence'})['policy'],'','See metrics.csv for separate deterministic metrics and human_review.csv for blank review fields.']
    (directory/'summary.md').write_text('\n'.join(lines)+'\n')
    return report
