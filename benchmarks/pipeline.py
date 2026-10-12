"""Small live end-to-end stacks with only synthetic in-memory retrieval."""
import json,time,argparse
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from .cases import load_fixture
from .retrieval import MemoryCollection,DEFAULTS
import ai_provider


def run_pipeline(encoder,embedding,model,threshold=.65,reranker=None):
    from retrieval import retrieve_evidence,RetrievalResult
    from student_support_agent import answer_question
    data=load_fixture();prefix='Represent this sentence for searching relevant passages: ' if embedding=='BAAI/bge-small-en-v1.5' else ''
    collection=MemoryCollection(data['corpus'],encoder,prefix);rows=[]
    for identity in ('t1','t4','t8'):
        query=next(q for q in data['retrieval'] if q['id']==identity);measurements=[]
        def retrieval(question,filters,**kwargs):
            result=retrieve_evidence(question,filters,collection=collection,candidate_k=15,final_k=15 if reranker else 5,max_distance=threshold)
            if reranker and result.evidence:
                scores=reranker.predict([(question,c.text) for c in result.evidence])
                evidence=tuple(c for _,c in sorted(zip(scores,result.evidence),key=lambda pair:-float(pair[0])))[:5]
                return RetrievalResult(evidence,result.diagnostics)
            return result
        def generation(*,messages):
            measured=ai_provider.generate_chat_measured(messages,model=model,options=dict(temperature=0,seed=17,num_ctx=4096,num_predict=1536),think=False,timeout_seconds=60)
            measurements.append(asdict(measured));return measured.text
        start=time.perf_counter();row=dict(query_id=identity,model=model,embedding=embedding,threshold=threshold,reranker=reranker is not None,human_groundedness='REQUIRES_HUMAN_REVIEW')
        try:
            with patch('student_support_agent.retrieve_evidence',retrieval),patch('ai_provider.generate_chat',generation):
                answer=answer_question(query['question'],filters=query['filters'])
            row.update(status='ok',answer=answer.answer,sources=answer.sources,retrieved_ids=[e.chunk_id for e in answer.retrieval.evidence],model_calls=len(measurements),model_measurements=measurements,expected_relevant_ids=query['relevant_ids'])
        except (ValueError,ai_provider.AIProviderError) as exc:row.update(status='failed',error_type=type(exc).__name__)
        row['total_latency_seconds']=time.perf_counter()-start;rows.append(row)
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);parser.add_argument('--embedding',required=True);parser.add_argument('--threshold',type=float,default=.65);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    from .models import GENERATIVE,EMBEDDINGS
    if args.model not in {c.model for c in GENERATIVE} or args.embedding not in {c.model for c in EMBEDDINGS[:2]}:raise ValueError('Use reviewed local models only.')
    output=Path(args.output).resolve();root=Path(__file__).resolve().parents[1]
    if output.is_relative_to(root) and not output.is_relative_to(root/'benchmarks'/'results'):raise ValueError('Use isolated output.')
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(2)
    encoder=SentenceTransformer(args.embedding,device='cpu',local_files_only=True)
    rows=run_pipeline(encoder,args.embedding,args.model,args.threshold)
    output.mkdir(parents=True,exist_ok=True);(output/'pipeline.json').write_text(json.dumps(rows,indent=2))
    print([(r['query_id'],r['status'],r.get('model_calls'),r['total_latency_seconds']) for r in rows])

if __name__=='__main__':main()
