"""Explicit isolated embedding/reranker evaluation. No production collection access."""
import argparse,json,time,resource,hashlib,gc,shutil
from pathlib import Path
from datetime import datetime,timezone
from .cases import load_fixture
from .models import EMBEDDINGS,RERANKERS,disk_gate
from .retrieval import MemoryCollection,evaluate_collection,calibrate_threshold


def evaluate_encoder(encoder,model, *, reranker=None):
    data=load_fixture();start=time.perf_counter()
    # BGE v1.5 model card recommends an instruction on queries, not documents.
    prefix='Represent this sentence for searching relevant passages: ' if model=='BAAI/bge-small-en-v1.5' else ''
    collection=MemoryCollection(data['corpus'],encoder,prefix)
    encoded=time.perf_counter()-start
    queries=data['retrieval']
    baseline=evaluate_collection(collection,queries,.65)
    calibration=calibrate_threshold(baseline['observations'])
    selected=calibration['recommended_threshold']
    test=[q for q in queries if q['split']=='test']
    calibrated=evaluate_collection(collection,test,selected)
    result=dict(embedding=model,fixture_version=data['version'],corpus_count=len(data['corpus']),query_count=len(queries),device='cpu',query_prefix=prefix,corpus_encode_seconds=encoded,baseline_current_settings=baseline,threshold_calibration=calibration,calibrated_heldout=calibrated,peak_process_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,utc=datetime.now(timezone.utc).isoformat(),store='In-memory cosine store explicitly injected into existing retrieval; no Chroma migration.')
    if reranker is not None:result['reranked_heldout']=evaluate_collection(collection,test,selected,reranker)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True,choices=[c.model for c in EMBEDDINGS]);parser.add_argument('--reranker',choices=[c.model for c in RERANKERS]);parser.add_argument('--output',required=True);parser.add_argument('--allow-download',action='store_true')
    args=parser.parse_args()
    # Deliberately prevent large components under this laptop's audited pressure.
    if args.model=='BAAI/bge-m3' or args.reranker=='BAAI/bge-reranker-v2-m3':raise SystemExit('Resource gate: large multilingual components deferred to server hardware.')
    output=Path(args.output).resolve()
    root=Path(__file__).resolve().parents[1]
    if output.is_relative_to(root) and not output.is_relative_to(root/'benchmarks'/'results'):raise ValueError('Use isolated benchmarks/results output.')
    output.mkdir(parents=True,exist_ok=True)
    status=dict(embedding=args.model,reranker=args.reranker,status='starting')
    try:
        import torch
        from sentence_transformers import SentenceTransformer,CrossEncoder
        torch.set_num_threads(2)
        candidate=next(c for c in EMBEDDINGS if c.model==args.model)
        gate=disk_gate(candidate,Path.home())
        if args.allow_download and not gate['allowed']:raise RuntimeError('Disk reserve gate rejected embedding download.')
        print('Embedding disk gate',gate,flush=True)
        started=time.perf_counter()
        encoder=SentenceTransformer(args.model,device='cpu',local_files_only=not args.allow_download)
        loaded=time.perf_counter()-started
        result=evaluate_encoder(encoder,args.model)
        result['embedding_load_seconds']=loaded
        # Save embedding-only evidence before attempting resource-heavier reranking.
        (output/'retrieval.json').write_text(json.dumps(result,indent=2))
        if args.reranker:
            candidate=next(c for c in RERANKERS if c.model==args.reranker)
            gate=disk_gate(candidate,Path.home())
            if args.allow_download and not gate['allowed']:raise RuntimeError('Disk reserve gate rejected reranker download.')
            print('Reranker disk gate',gate,flush=True)
            started=time.perf_counter()
            reranker=CrossEncoder(args.reranker,device='cpu',local_files_only=not args.allow_download)
            reranker_load=time.perf_counter()-started
            # Reuse encoder weights; rebuild deterministic synthetic store only.
            result=evaluate_encoder(encoder,args.model,reranker=reranker)
            result.update(embedding_load_seconds=loaded,reranker=args.reranker,reranker_load_seconds=reranker_load)
            (output/'retrieval.json').write_text(json.dumps(result,indent=2))
        status['status']='completed'
    except Exception as exc:
        # No raw external exception/body is written; failed benchmark is explicit.
        status.update(status='failed',error_type=type(exc).__name__,error='Model unavailable, download failure or resource/runtime error. Embedding-only evidence retained if completed.')
        print('FAILED',type(exc).__name__,flush=True)
    (output/'status.json').write_text(json.dumps(status,indent=2))
    if status['status']=='failed':raise SystemExit(1)

if __name__=='__main__':main()
