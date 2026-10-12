"""Expanded isolated retrieval evaluation; calibration excludes held-out data."""
import json,argparse,time,resource
from pathlib import Path
from .cases_v2 import load_v2
from .retrieval import MemoryCollection,evaluate_collection,calibrate_threshold

def evaluate(encoder,model):
    data=json.loads((Path(__file__).parent/'fixtures'/'retrieval_synthetic_v2.json').read_text());prefix='Represent this sentence for searching relevant passages: ' if model=='BAAI/bge-small-en-v1.5' else ''
    start=time.perf_counter();collection=MemoryCollection(data['corpus'],encoder,prefix)
    encoded=time.perf_counter()-start;baseline=evaluate_collection(collection,data['retrieval'],.65)
    calibration=calibrate_threshold(baseline['observations']);test=[q for q in data['retrieval'] if q['split']=='test']
    return dict(version='retrieval-v2',embedding=model,corpus_count=len(data['corpus']),query_count=len(data['retrieval']),corpus_encode_seconds=encoded,baseline=baseline,calibration=calibration,heldout=evaluate_collection(collection,test,calibration['recommended_threshold']),peak_python_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',choices=['sentence-transformers/all-MiniLM-L6-v2','BAAI/bge-small-en-v1.5'],required=True);p.add_argument('--output',required=True);args=p.parse_args()
    output=Path(args.output).resolve();root=Path(__file__).resolve().parents[1]
    if output.is_relative_to(root) and not output.is_relative_to(root/'benchmarks'/'results'):raise ValueError('Isolated output only.')
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(2);encoder=SentenceTransformer(args.model,device='cpu',local_files_only=True)
    result=evaluate(encoder,args.model);output.mkdir(parents=True,exist_ok=True);(output/'retrieval.json').write_text(json.dumps(result,indent=2));print(result['heldout']['metrics'])
if __name__=='__main__':main()
