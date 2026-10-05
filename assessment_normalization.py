"""Known equivalent MCQ option shape only. No JSON or semantic repair."""
from dataclasses import dataclass
from copy import deepcopy

NORMALIZATION_TYPE='known_mcq_option_shape'

@dataclass(frozen=True)
class NormalizationResult:
    data: dict
    applied: bool = False
    normalization_type: str | None = None


def normalize_assessment(data):
    result=deepcopy(data);changed=False
    questions=result.get('questions')
    if not isinstance(questions,list):return NormalizationResult(result)
    for q in questions:
        if not isinstance(q,dict) or q.get('question_type')!='MCQ' or not isinstance(q.get('options'),list):continue
        options=q['options']
        if len(options)!=4:raise ValueError('MCQ compatibility shape requires four options.')
        normalized={}
        for entry in options:
            if not isinstance(entry,dict) or len(entry)!=1:raise ValueError('Ambiguous MCQ compatibility shape.')
            label,value=next(iter(entry.items()))
            if not isinstance(label,str) or label not in 'ABCD' or len(label)!=1 or label in normalized or not isinstance(value,str) or not value.strip():raise ValueError('Invalid MCQ compatibility option.')
            normalized[label]=value
        if set(normalized)!=set('ABCD'):raise ValueError('Incomplete MCQ compatibility options.')
        q['options']={k:normalized[k] for k in 'ABCD'};changed=True
    return NormalizationResult(result,changed,NORMALIZATION_TYPE if changed else None)
