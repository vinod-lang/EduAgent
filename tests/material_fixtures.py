"""A deterministic exact-ID vector substitute; never opens real Chroma."""
import copy

class Vectors:
    def __init__(self):
        self.rows = {}
        self.fail_add = self.fail_delete = self.fail_update = False

    def add_material_chunks(self, ids, chunks, metadata):
        for key, text in zip(ids, chunks):
            self.rows[key] = {'document': text, 'metadata': dict(metadata)}
        if self.fail_add:
            raise RuntimeError('synthetic insertion failure after partial write')

    def get_material_chunks(self, ids):
        present = [i for i in ids if i in self.rows]
        return {'ids': present, 'metadatas': [copy.deepcopy(self.rows[i]['metadata']) for i in present], 'documents': [self.rows[i]['document'] for i in present]}

    def delete_material_chunks(self, ids):
        if self.fail_delete:
            raise RuntimeError('synthetic deletion failure')
        for key in ids:
            self.rows.pop(key, None)

    def update_material_chunks(self, ids, metadatas):
        if self.fail_update:
            raise RuntimeError('synthetic metadata failure')
        for key, metadata in zip(ids, metadatas):
            self.rows[key]['metadata'].update(copy.deepcopy(metadata))
