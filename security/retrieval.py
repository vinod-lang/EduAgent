"""Mandatory allowlist pushed into the vector query BEFORE evidence is retrieved."""
from application.errors import ValidationError

class AuthorizedCollection:
    def __init__(self,allowed_ids,collection_factory,verify=None):
        self.allowed_ids=tuple(allowed_ids);self.factory=collection_factory;self._collection=None;self.verify=verify
    def _get(self):
        if self._collection is None:self._collection=self.factory()
        return self._collection
    @property
    def configuration(self):
        return self._get().configuration if self.allowed_ids else {'hnsw':{'space':'cosine'}}
    def constraint(self):return {'material_id':{'$in':list(self.allowed_ids)}}
    def count(self):
        if not self.allowed_ids:return 0
        return len(self._get().get(where=self.constraint(),include=[])['ids'])
    def query(self,*,where=None,**kwargs):
        if not self.allowed_ids:return {'ids':[[]],'documents':[[]],'metadatas':[[]],'distances':[[]]}
        if self.verify is not None and not self.verify(self.allowed_ids):raise ValidationError()
        constraint=self.constraint()
        raw=self._get().query(where={'$and':[constraint,where]} if where else constraint,**kwargs)
        # Defense in depth against a faulty adapter, still before any LLM call.
        metadata=raw.get('metadatas',[[]])[0]
        if any(not isinstance(m,dict) or m.get('material_id') not in self.allowed_ids for m in metadata):raise ValidationError()
        if len(metadata)!=len(raw.get('ids',[[]])[0]):raise ValidationError()
        if self.verify is not None and not self.verify(self.allowed_ids):raise ValidationError()
        return raw


    @property
    def supports_adjacent(self):
        import inspect
        getter=getattr(self._get(),'get',None)
        if not callable(getter):return False
        parameters=inspect.signature(getter).parameters
        return 'ids' in parameters or any(p.kind==p.VAR_KEYWORD for p in parameters.values())

    def get(self,*,ids,where=None,include=None):
        """Exact neighbor reads retain both authorization and academic constraints."""
        if not self.allowed_ids:return {'ids':[],'documents':[],'metadatas':[]}
        if self.verify is not None and not self.verify(self.allowed_ids):raise ValidationError()
        constraint=self.constraint()
        raw=self._get().get(ids=ids,where={'$and':[constraint,where]} if where else constraint,include=include)
        metadata=raw.get('metadatas',[])
        if len(metadata)!=len(raw.get('ids',[])) or any(not isinstance(m,dict) or m.get('material_id') not in self.allowed_ids for m in metadata):raise ValidationError()
        if any(identity not in ids for identity in raw.get('ids',[])):raise ValidationError()
        if self.verify is not None and not self.verify(self.allowed_ids):raise ValidationError()
        return raw
