"""Bounded drafting checks, not semantic truth or subjective writing scores."""
import re
import unicodedata
from document_models import DocumentError
from generation_trace import stage
from structured_generation import DocumentQualityFailure, FactPreservationFailure, UnsupportedGeneratedFactFailure

MONTHS=r'January|February|March|April|May|June|July|August|September|October|November|December'
FACT_PATTERN=re.compile(r'(?:₹|\$|€|£|\bINR\s*|\bRs\.?\s*)\d[\d,]*(?:\.\d+)?|\b\d{1,2}\s+(?:'+MONTHS+r')\s+\d{4}\b|\b(?:budget|amount|cost|expenditure)\s+(?:(?:is|of)\s+)?\d[\d,]*(?:\.\d+)?|\b\d{4}-\d{2}-\d{2}\b|\b\d+\s+(?:students|attendees|participants)\b',re.I)

def normalized(text):
    text=unicodedata.normalize('NFKC',text).casefold()
    text=re.sub(r'(?<=\d),(?=\d)','',text)
    text=re.sub(r'₹|\binr\b|\brs\.?',' currency ',text)
    return ' '.join(re.findall(r'\w+(?:\.\d+)?',text))


def body_fact_present(value,body):
    """Allow formatting/connective changes, never arbitrary semantic similarity.

    Exact phrases remain valid. Narrow financial facts allow currency notation,
    grouping commas and optional connective words; numeric boundaries remain exact.
    Other prose facts require their normalized full phrase, not guessed synonyms.
    """
    expected=normalized(value);actual=normalized(body)
    if re.search(r'(?<!\w)'+re.escape(expected)+r'(?!\w)',actual):
        # Reject explicit negation immediately attached to the matching fact.
        return not re.search(r'\b(?:not|never|no)\s+(?:\w+\s+){0,2}'+re.escape(expected)+r'(?!\w)',actual)
    match=re.fullmatch(r'(budget|amount|cost|expenditure)\s+(?:currency\s+)?(\d+(?:\.\d+)?)',expected)
    if match:
        return bool(re.search(r'\b'+match[1]+r'\s+(?:(?:of|is|the|proposed|estimated)\s+)*(?:currency\s+)?'+re.escape(match[2])+r'(?![\w.])',actual)) and not bool(re.search(r'\b(?:not|never|no)\b',actual))
    return False


def critical_values(text):
    values=set()
    for m in FACT_PATTERN.finditer(text):
        value=normalized(m.group())
        if re.match(r'^(?:budget|amount|cost|expenditure)\b',value):value='currency '+re.search(r'\d+(?:\.\d+)?',value).group()
        values.add(value)
    return values


# Recognizable template tokens only; citations and ordinary brackets are allowed.
_PLACEHOLDER=re.compile(r'\[([^\]\n]{1,100})\]|\{\{([^{}\n]{1,100})\}\}|<([^<>\n]{1,100})>')
_PLACEHOLDER_LABEL=re.compile(r'(?:(?:specific|insert|enter|provide|your)\s+)?(?:date|time|venue|location|amount|reference(?: number)?|name|sender|recipient|signature|department|institution|budget|deadline|TBD|TODO)(?:\s+here)?',re.I)

def unresolved_placeholder(text):
    return bool(re.search(r'\b(?:TBD|TODO|TO BE FILLED)\b',text)) or any(
        _PLACEHOLDER_LABEL.fullmatch(next(v for v in match.groups() if v is not None).strip())
        or re.fullmatch(r'(?:insert|enter|provide)\s+.{1,80}',next(v for v in match.groups() if v is not None).strip(),re.I)
        for match in _PLACEHOLDER.finditer(text))

# Narrow explicit assertions, not general semantic English classification.
_PREPARED=re.compile(r"\b(?:I|we)\s+have\s+(?:already\s+)?(?:prepared|completed|attached|enclosed|submitted)\s+(?:(?:a|the|our|my|detailed)\s+){0,3}(?:budget|report|plan|proposal|attachment|document)\b[^.!?\n]{0,200}",re.I)
_FUNDED=re.compile(r"\b(?:all\s+)?expenses\s+(?:(?:will be|are|were|have been)\s+)?covered\s+by\s+[^.!?\n]{1,200}",re.I)
_REFERENCE=re.compile(r"\b(?:reference\s+(?:number|no\.?)|ref\.?)\s*[:#]\s*([A-Za-z0-9][A-Za-z0-9/-]{1,50})",re.I)


def validate_quality(draft):
    for value in [*draft.body,*(getattr(draft,k) for k in ('title','recipient','sender','date','reference_number','subject','salutation','closing','signature'))]:
        if unresolved_placeholder(value):
            stage('quality',False,failure_field='body',failure_rule='placeholder')
            raise DocumentQualityFailure('The draft contains an unresolved template placeholder.',rule='placeholder')
    for paragraph in draft.body:
        stripped=paragraph.strip()
        if not re.search(r'\w',stripped):stage('quality',False,failure_field='body',failure_rule='empty_body');raise DocumentQualityFailure('The draft has no meaningful body content.')
        if re.fullmatch(r'(?:\[[^\]]*\]|\{[^}]*\}|<[^>]*>|(?:TBD|TODO|N/?A)[.!]*)',stripped,re.I):
            stage('quality',False,failure_field='body',failure_rule='placeholder');raise DocumentQualityFailure('The draft contains an unfilled placeholder paragraph.',rule='placeholder')
        if re.search(r'\b(?:scheduled (?:to take place|for)|will be held|takes place|budget (?:is|of)|amount (?:is|of))\s*(?:on|at|in|for|of)?\s*[.!:]*$',stripped,re.I):
            stage('quality',False,failure_field='body',failure_rule='incomplete_sentence');raise DocumentQualityFailure('The draft contains an incomplete factual sentence.')
        if re.search(r'\b(?:as an ai|insert (?:date|amount|venue) here)\b',stripped,re.I):
            stage('quality',False,failure_field='body',failure_rule='drafting_commentary');raise DocumentQualityFailure('The draft contains drafting commentary or placeholders.')
    return draft


def validate_factual_values(draft,source,*,preserve=False):
    old=critical_values(source)
    old.update('currency '+m.group(1).replace(',','') for m in re.finditer(r'\bbudget\s+(\d[\d,]*(?:\.\d+)?)',source,re.I))
    body=' '.join(draft.body);new=critical_values(body)
    # Missing protected values take precedence over repairable new assertions.
    if preserve and critical_values(source)-new-critical_values(' '.join(getattr(draft,k) for k in ('date','reference_number','recipient','sender','title','subject','signature'))):
        stage('fact_validation',False,failure_field='body',failure_rule='protected_fact_changed')
        raise FactPreservationFailure('A supplied factual value was removed or changed.')
    for pattern in (_PREPARED,_FUNDED):
        for claim in pattern.finditer(body):
            if normalized(claim.group()) not in normalized(source):
                stage('fact_validation',False,failure_field='body',failure_rule='unsupported_factual_value')
                raise UnsupportedGeneratedFactFailure('An unsupported preparation or funding assertion was supplied.')
    for claim in _REFERENCE.finditer(body):
        if not re.search(r'(?<![\w/-])'+re.escape(claim.group(1))+r'(?![\w/-])',source,re.I):
            stage('fact_validation',False,failure_field='reference_number',failure_rule='unsupported_factual_value')
            raise UnsupportedGeneratedFactFailure('An unsupported reference number was supplied.')
    for claim in re.findall(r'(?:venue|location)\s*(?:is|:)\s*([^.!?]+)',body,re.I):
        if normalized(claim) not in normalized(source):stage('fact_validation',False,failure_field='body',failure_rule='unsupported_location');raise FactPreservationFailure('An unsupported location was supplied.')
    if re.search(r'\bapproval (?:has been|is|was) granted\b',body,re.I) and not re.search(r'\bapproval (?:has been|is|was) granted\b',source,re.I):
        stage('fact_validation',False,failure_field='body',failure_rule='invented_approval');raise FactPreservationFailure('A granted approval was invented.')
    if new-old or (preserve and critical_values(source)-new-critical_values(' '.join(getattr(draft,k) for k in ('date','reference_number','recipient','sender','title','subject','signature')))):
        stage('fact_validation',False,failure_field='body',failure_rule='unsupported_factual_value');raise (FactPreservationFailure if old else UnsupportedGeneratedFactFailure)('A protected date, amount or count was invented or changed.')
    return draft
