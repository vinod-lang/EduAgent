"""In-memory synthetic cosine store injected into existing RAG; never production Chroma."""
import math,time
import numpy as np
from retrieval import retrieve_evidence
from .cases import load_fixture

DEFAULTS={'candidate_k':15,'final_k':5,'max_distance':.65}


def retrieval_metrics(rankings,queries,k=5):
    if type(k)is not int or k<1:raise ValueError('K must be positive.')
    if len(rankings)!=len(queries):raise ValueError('Ranking/query length mismatch.')
    positive=[];negative=[];scope=[]
    for ranking,query in zip(rankings,queries):
        ids=[r['id'] if isinstance(r,dict) else r for r in ranking]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate ranked IDs.')
        relevant=set(query['relevant_ids'])
        if relevant:
            positive.append(dict(hit1=int(bool(relevant&set(ids[:1]))),hit3=int(bool(relevant&set(ids[:3]))),hit5=int(bool(relevant&set(ids[:5]))),recall=len(relevant&set(ids[:k]))/len(relevant),rr=next((1/(i+1) for i,x in enumerate(ids) if x in relevant),0)))
        else:negative.append(int(bool(ids)))
        # Unknown metadata cannot be counted as a successful hierarchy check.
        scope.append(all(isinstance(r,dict) and all(r.get(key)==value for key,value in query['filters'].items()) for r in ranking))
    def mean(values):return sum(values)/len(values) if values else None
    return dict(hit_at_1=mean([r['hit1'] for r in positive]),hit_at_3=mean([r['hit3'] for r in positive]),hit_at_5=mean([r['hit5'] for r in positive]),recall_at_k=mean([r['recall'] for r in positive]),k=k,mrr=mean([r['rr'] for r in positive]),no_evidence_false_positive_rate=mean(negative),hierarchy_filter_correctness=mean(scope),positive_queries=len(positive),negative_queries=len(negative))


def calibrate_threshold(rows,thresholds=None):
    rows=[r for r in rows if r['split']=='calibration']
    if not any(r['relevant_ids'] for r in rows) or not any(not r['relevant_ids'] for r in rows):raise ValueError('Calibration needs positive and no-evidence queries.')
    thresholds=list(thresholds) if thresholds is not None else [round(i/20,2) for i in range(1,20)]
    if not thresholds or any(not isinstance(t,(int,float)) or not math.isfinite(t) or not 0<=t<=2 for t in thresholds):raise ValueError('Invalid thresholds.')
    curve=[]
    for threshold in sorted(set(thresholds)):
        positives=[r for r in rows if r['relevant_ids']];negatives=[r for r in rows if not r['relevant_ids']]
        hit=sum(any(c['id'] in r['relevant_ids'] and c['distance']<=threshold for c in r['candidates'][:5]) for r in positives)/len(positives)
        fpr=sum(any(c['distance']<=threshold for c in r['candidates'][:15]) for r in negatives)/len(negatives)
        curve.append(dict(threshold=threshold,positive_hit_rate=hit,no_evidence_fpr=fpr,balanced_accuracy=(hit+1-fpr)/2))
    best=max(curve,key=lambda r:(r['balanced_accuracy'],-r['threshold']))
    return dict(recommended_threshold=best['threshold'],selection='Calibration-only balanced accuracy; ties choose lower cutoff. Held-out test never used to select.',curve=curve)


class MemoryCollection:
    configuration={'hnsw':{'space':'cosine'}}
    def __init__(self,rows,encoder,query_prefix=''):
        self.rows=rows;self.encoder=encoder;self.query_prefix=query_prefix
        self.vectors=np.asarray(encoder.encode([r['text'] for r in rows],normalize_embeddings=True),dtype=float)
        if self.vectors.ndim!=2 or len(self.vectors)!=len(rows) or not np.isfinite(self.vectors).all() or np.any(np.linalg.norm(self.vectors,axis=1)==0):raise ValueError('Invalid embeddings.')
        self.cache={}
    def count(self):return len(self.rows)
    @staticmethod
    def matches(row,where):
        if not where:return True
        if '$and' in where:return all(MemoryCollection.matches(row,w) for w in where['$and'])
        return all(row.get(k)==v for k,v in where.items())
    def query(self,query_texts,n_results,where=None,include=None):
        question=query_texts[0]
        if question not in self.cache:
            self.cache[question]=np.asarray(self.encoder.encode([self.query_prefix+question],normalize_embeddings=True),dtype=float)[0]
        q=self.cache[question]
        if q.ndim!=1 or len(q)!=self.vectors.shape[1] or not np.isfinite(q).all() or np.linalg.norm(q)==0:raise ValueError('Invalid query embedding.')
        eligible=[(max(0.,min(2.,float(1-self.vectors[i]@q))),r) for i,r in enumerate(self.rows) if self.matches(r,where)]
        eligible.sort(key=lambda pair:(pair[0],pair[1]['id']));chosen=eligible[:n_results]
        return dict(ids=[[r['id'] for _,r in chosen]],documents=[[r['text'] for _,r in chosen]],metadatas=[[{k:v for k,v in r.items() if k not in ('id','text')} for _,r in chosen]],distances=[[d for d,_ in chosen]])


def evaluate_collection(collection,queries,threshold=.65,reranker=None):
    rankings=[];rows=[];latencies=[]
    for query in queries:
        started=time.perf_counter()
        # Explicit injection keeps current production retrieval/dedup/filter rules.
        actual=retrieve_evidence(query['question'],query['filters'],candidate_k=15,final_k=15 if reranker is not None else 5,max_distance=threshold,collection=collection)
        selected=list(actual.evidence)
        if reranker is not None and selected:
            scores=reranker.predict([(query['question'],c.text) for c in selected])
            if len(scores)!=len(selected) or not np.isfinite(scores).all():raise ValueError('Invalid reranker scores.')
            selected=[c for _,c in sorted(zip(scores,selected),key=lambda pair:-float(pair[0]))]
        selected=selected[:5]
        latencies.append(time.perf_counter()-started)
        # Untuned candidate observations for calibration are collected after the
        # timed production-equivalent retrieval; they do not change its output.
        candidates=retrieve_evidence(query['question'],query['filters'],candidate_k=15,final_k=15,max_distance=2,collection=collection)
        rankings.append([dict(id=c.chunk_id,course=c.course,semester=c.semester,subject=c.subject,unit=c.unit) for c in selected])
        rows.append(dict(query_id=query['id'],split=query['split'],relevant_ids=query['relevant_ids'],candidates=[dict(id=c.chunk_id,distance=c.distance) for c in candidates.evidence]))
    return dict(metrics=retrieval_metrics(rankings,queries),rankings=rankings,observations=rows,query_latency_seconds=latencies,settings=dict(DEFAULTS,max_distance=threshold),query_cache='Each query encoded once per collection; subsequent threshold/rerank runs reuse identical vectors.')
