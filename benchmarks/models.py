"""Candidate manifest and explicit resource gates; no download at import/run."""
from dataclasses import dataclass,asdict
import shutil

RESERVE_BYTES=15*1024**3
@dataclass(frozen=True)
class Candidate:
    model:str
    estimated_bytes:int
    purpose:str
    license:str
    source:str

GENERATIVE=(
 Candidate('llama3.2:3b',2_000_000_000,'Existing production baseline','Llama 3.2 Community License','https://ollama.com/library/llama3.2'),
 Candidate('qwen3:1.7b',1_400_000_000,'Small instruction/tool-planning candidate, non-thinking for comparable latency','Apache-2.0','https://ollama.com/library/qwen3:1.7b'),
 Candidate('qwen3.5:0.8b',1_000_000_000,'Modern compact speed candidate, non-thinking','Apache-2.0','https://ollama.com/library/qwen3.5:0.8b'))
EMBEDDINGS=(
 Candidate('sentence-transformers/all-MiniLM-L6-v2',92_000_000,'Current English embedding baseline','Apache-2.0','https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2'),
 Candidate('BAAI/bge-small-en-v1.5',134_000_000,'Retrieval-trained lightweight English challenger fitting this laptop','MIT','https://huggingface.co/BAAI/bge-small-en-v1.5'),
 Candidate('BAAI/bge-m3',2_270_000_000,'Future multilingual comparison; not safe under current swap pressure','MIT','https://huggingface.co/BAAI/bge-m3'))
RERANKERS=(Candidate('BAAI/bge-reranker-base',1_110_000_000,'Smallest justified BGE cross-encoder comparison','MIT','https://huggingface.co/BAAI/bge-reranker-base'),Candidate('BAAI/bge-reranker-v2-m3',2_270_000_000,'Future multilingual candidate; skip current laptop','Apache-2.0','https://huggingface.co/BAAI/bge-reranker-v2-m3'))


def download_gate(candidate,free_bytes, *, reserve=RESERVE_BYTES,overhead=1.15):
    if free_bytes<0 or reserve<0 or overhead<1:raise ValueError('Invalid resource estimate.')
    estimate=int(candidate.estimated_bytes*overhead)
    return dict(allowed=free_bytes-estimate>=reserve,free_bytes=free_bytes,estimated_download_bytes=estimate,reserve_bytes=reserve)


def disk_gate(candidate,path):return download_gate(candidate,shutil.disk_usage(path).free)
