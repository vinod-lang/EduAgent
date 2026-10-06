"""Strictly local ingestion/analytics; no AI, Activity Log or student persistence."""
from __future__ import annotations
from typing import TYPE_CHECKING
from ._dependencies import dependency
from .errors import call
from .models import StudentAnalysis
if TYPE_CHECKING:
    from student_ingestion import Workbook, NormalizedDataset, Mapping, RawTable
    from analytics_agent import Thresholds

class StudentService:
    def __init__(self, *, ingestion=None, hub=None): self.ingestion=ingestion; self.hub=hub
    def parse(self,data: bytes,filename: str) -> Workbook: return call(dependency(self.ingestion,'student_ingestion').parse_student_file,data,filename)
    def headers(self,sheet): return call(dependency(self.ingestion,'student_ingestion').header_candidates,sheet)
    def table(self,sheet,header_row): return call(dependency(self.ingestion,'student_ingestion').make_raw_table,sheet,header_row)
    def suggest(self,table): return call(dependency(self.ingestion,'student_ingestion').suggest_columns,table)
    def normalize(self,table: RawTable,mapping: Mapping) -> NormalizedDataset: return call(dependency(self.ingestion,'student_ingestion').normalize_dataset,table,mapping)
    def analyze_dataset(self,dataset,thresholds=None): return call(dependency(self.hub,'student_hub').analyze_dataset,dataset,thresholds)
    def filter(self,frame,view='All',search=''): return call(dependency(self.hub,'student_hub').filter_students,frame,view,search)
    def analyze(self,dataset: NormalizedDataset,thresholds: Thresholds | None=None,*,view='All',search='') -> StudentAnalysis:
        frame,summary=self.analyze_dataset(dataset,thresholds)
        return StudentAnalysis(self.filter(frame,view,search),summary)
    def public(self,frame): return call(dependency(self.hub,'student_hub').public_results,frame)
    def csv(self,frame): return call(dependency(self.hub,'student_hub').result_csv_bytes,frame)
    def validation_csv(self,dataset): return call(dependency(self.hub,'student_hub').validation_csv_bytes,dataset)
