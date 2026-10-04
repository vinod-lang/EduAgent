"""Opt-in command-line benchmark; no application imports execute it."""
import argparse,json,time,platform,resource,hashlib
from datetime import datetime,timezone
from pathlib import Path
import ai_provider
from .cases import generative_cases,load_fixture
from .models import GENERATIVE
from .scoring import score
from .report import write_report


def run_models(models,installed, *, call=None,repeats=2,timeout=60,progress=None):
    if type(repeats)is not int or not 1<=repeats<=10:raise ValueError('Repeated runs must be 1–10.')
    if not models or len(set(models))!=len(models):raise ValueError('Provide unique benchmark models.')
    allowed={c.model for c in GENERATIVE}
    if not set(models)<=allowed:raise ValueError('Use reviewed benchmark candidate identifiers.')
    cases=generative_cases();runs=[];call=call or ai_provider.generate_chat_measured
    for model in models:
        for case in cases:
            for repeat in range(repeats if case.structured else 1):
                started=time.perf_counter()
                row=dict(model=model,category=case.category,case_id=case.case_id,repeat=repeat,status='ok',scores={},response=None)
                options=dict(temperature=0,seed=17+repeat,num_ctx=4096,num_predict=1536)
                row['configuration']=dict(options=options,think=False,timeout_seconds=timeout,stream=False)
                if model not in installed:
                    row.update(status='unavailable',elapsed_seconds=None,error='Model not installed; not pulled automatically.')
                else:
                    try:
                        measured=call(list(case.messages),model=model,options=options,think=False,timeout_seconds=timeout)
                        row.update(response=measured.text,elapsed_seconds=measured.elapsed_seconds,output_bytes=len(measured.text.encode()),output_tokens=measured.output_tokens,prompt_tokens=measured.prompt_tokens,total_duration_ns=measured.total_duration_ns,load_duration_ns=measured.load_duration_ns,eval_duration_ns=measured.eval_duration_ns,scores=score(case,measured.text))
                    except ai_provider.AIProviderError as exc:
                        cause=exc.__cause__
                        row.update(status='timeout' if isinstance(cause,TimeoutError) or cause is not None and 'Timeout' in type(cause).__name__ else 'provider_error',elapsed_seconds=time.perf_counter()-started,error=type(exc).__name__)
                    except (ValueError,TypeError,KeyError) as exc:
                        row.update(status='scoring_error',elapsed_seconds=time.perf_counter()-started,error=type(exc).__name__)
                row['validation_status']='invalid' if row.get('scores',{}).get('schema_valid')==0 else 'valid' if row.get('scores',{}).get('schema_valid')==1 else 'not_applicable'
                row['validation_failed_checks']=[k for k,v in row.get('scores',{}).items() if v==0 and k!='duplicate_question_rate']
                runs.append(row)
                if progress:progress(row,runs)
    return dict(fixture_version=load_fixture()['version'],utc=datetime.now(timezone.utc).isoformat(),platform=platform.platform(),python=platform.python_version(),prompt_fingerprints={c.case_id:hashlib.sha256(json.dumps(c.messages,sort_keys=True).encode()).hexdigest() for c in cases},protocol='build13-pilot-v1',runs=runs,repeats_structured=repeats,repeats_qa=1,ttft='Not available: non-streaming complete-response latency measured.',peak_process_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,production_changes='None; no automatic routing or reindex.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',action='append',required=True);parser.add_argument('--output',required=True);parser.add_argument('--repeats',type=int,default=2)
    args=parser.parse_args()
    # Local HTTP read only; no installed-model download/start side effect.
    import httpx
    from config import get_ai_config
    try:
        response=httpx.get(get_ai_config().base_url+'/api/tags',timeout=5);response.raise_for_status()
        tags=response.json()['models'];installed={m['name'] for m in tags}
    except (httpx.HTTPError,KeyError,ValueError):tags=[];installed=set()
    output=Path(args.output).resolve()
    root=Path(__file__).resolve().parents[1]
    if output.is_relative_to(root) and not output.is_relative_to(root/'benchmarks'/'results'):raise ValueError('Use isolated benchmarks/results output.')
    output.mkdir(parents=True,exist_ok=True)
    def progress(row,runs):
        try:
            resident=httpx.get(get_ai_config().base_url+'/api/ps',timeout=5).json().get('models',[])
            row['observed_ollama_residency']=[{k:m.get(k) for k in ('name','size','size_vram','context_length')} for m in resident]
        except (httpx.HTTPError,ValueError):row['observed_ollama_residency']=None
        print(row['model'],row['case_id'],row['repeat'],row['status'],round(row['elapsed_seconds'] or 0,2),flush=True)
        (output/'progress.json').write_text(json.dumps(runs,indent=2))
    result=run_models(args.model,installed,repeats=args.repeats,progress=progress)
    result['installed_models']=tags
    hardware=Path(__file__).parent/'results'/'hardware.json'
    result['hardware_audit']=json.loads(hardware.read_text()) if hardware.exists() else None
    write_report(result,output)

if __name__=='__main__':main()
