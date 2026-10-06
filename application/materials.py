"""Managed material use cases; existing lifecycle owns rollback and exact deletion."""
from ._dependencies import dependency
from .errors import call, NotFoundError
from .models import MaterialUpload

class MaterialService:
    def __init__(self, *, repository=None, lifecycle=None, uploads='uploads', vectors=None, extractor=None):
        self.repository=repository; self.lifecycle=lifecycle
        self.uploads=uploads; self.vectors=vectors; self.extractor=extractor
    def _repo(self): return dependency(self.repository,'db')
    def _lifecycle(self): return dependency(self.lifecycle,'material_service')
    def list_materials(self, course=None): return call(self._repo().list_materials, course)
    def courses(self): return call(self._repo().get_all_courses)
    def available_courses(self, materials=None):
        records=self.list_materials() if materials is None else materials
        return sorted(set(self.courses()) | {row['course'] for row in records})
    def get(self, material_id):
        record=call(self._repo().get_material,material_id)
        if record is None: raise NotFoundError()
        return record
    def hierarchy(self):
        from dashboard import build_material_tree
        return build_material_tree(self.list_materials(),self.courses())
    def scope_records(self):
        rows=list(self.list_materials())
        return rows+call(self._repo().assessment_legacy_scope_records)

    def _outcome(self, result):
        # Legacy rollback errors can contain client internals/paths. Never echo them.
        result=dict(result)
        safe_extraction_errors={
            'Upload failed: Image OCR is unavailable because Tesseract is not installed or configured.',
            'Upload failed: Image OCR is unavailable: pytesseract is not installed.',
            'Upload failed: Local image OCR failed or timed out.',
            'Upload failed: PDF could not be read.',
            'Upload failed: Image content does not match its PNG/JPEG extension.',
            'Upload failed: Image is corrupt, unsupported or too large to decode safely.',
            'Upload failed: Material contains no usable extracted text.',
        }
        if not result.get('success') and not result.get('duplicate') and result.get('error') not in safe_extraction_errors:
            result['error']='Material operation did not complete. Check storage availability; unresolved cleanup may require review.'
        result['warnings']=['A storage layer needs review; the operation may be incomplete.' for _ in result.get('warnings',())]
        return result
    def upload(self, request: MaterialUpload):
        return self.upload_material(request.content,request.filename,request.hierarchy)
    def upload_material(self, data, filename, hierarchy):
        return self._outcome(call(self._lifecycle().upload_material,data,filename,hierarchy,
            uploads=self.uploads,vectors=self.vectors,extractor=self.extractor))
    def delete(self, material_id):
        return self._outcome(call(self._lifecycle().delete_material,material_id,uploads=self.uploads,vectors=self.vectors))
    def edit_hierarchy(self, material_id, hierarchy):
        return self._outcome(call(self._lifecycle().edit_hierarchy,material_id,hierarchy,vectors=self.vectors))
