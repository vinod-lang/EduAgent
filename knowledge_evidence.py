"""Bounded adjacent context for Knowledge only; no embedding or storage imports."""
import os,re
from dataclasses import replace
from retrieval import RetrievalError,build_filter,normalize_results

def context_budget():
    try:value=int(os.environ.get('EDUAGENT_KNOWLEDGE_CONTEXT_CHARS','6000'))
    except ValueError:raise RetrievalError('Knowledge context budget must be an integer.') from None
    if not 500<=value<=20000:raise RetrievalError('Knowledge context budget must be between 500 and 20000 characters.')
    return value

def expand_context(seeds,collection,filters):
    budget=context_budget();selected=[];used=0;seen_ids=set();seen_text=set()
    # Reserve budget for actual nearest matches before adding surrounding context.
    for seed in seeds:
        if used+len(seed.text)<=budget:
            selected.append(seed);used+=len(seed.text);seen_ids.add(seed.chunk_id);seen_text.add(seed.text)
    neighbors={};requests={}
    for seed in selected:
        match=re.fullmatch(r'(.+)_chunk_(\d+)',seed.chunk_id)
        if not match or match[1]!=seed.material_id:continue
        n=int(match[2])
        for offset in (-1,1):
            if n+offset<0:continue
            identity=f'{seed.material_id}_chunk_{n+offset}'
            if identity not in seen_ids:requests[identity]=seed.material_id
    getter=getattr(collection,'get',None)
    if requests and callable(getter) and getattr(collection,'supports_adjacent',True):
        raw=getter(ids=list(requests),where=build_filter(filters),include=['documents','metadatas'])
        identities=raw.get('ids',[])
        converted=dict(ids=[identities],documents=[raw.get('documents',[])],metadatas=[raw.get('metadatas',[])],distances=[[0.0]*len(identities)])
        chunks,_,_=normalize_results(converted)
        for chunk in chunks:
            if requests.get(chunk.chunk_id)!=chunk.material_id:raise RetrievalError('Adjacent context crossed material ownership.')
            if any(getattr(chunk,key,None)!=value for key,value in filters.items() if key!='source') or (filters.get('source') and chunk.source!=filters['source']):raise RetrievalError('Adjacent context violated selected scope.')
            neighbors[chunk.chunk_id]=replace(chunk,distance=None,selection='adjacent')
    output=[]
    for seed in selected:
        match=re.fullmatch(r'(.+)_chunk_(\d+)',seed.chunk_id)
        previous=following=None
        if match:
            previous=neighbors.get(f'{match[1]}_chunk_{int(match[2])-1}')
            following=neighbors.get(f'{match[1]}_chunk_{int(match[2])+1}')
        for item in (previous,seed,following):
            if item is None or item.chunk_id in {v.chunk_id for v in output}:continue
            if item.selection=='adjacent':
                if item.text in seen_text or used+len(item.text)>budget:continue
                used+=len(item.text);seen_text.add(item.text)
            output.append(item)
    return tuple(output)
