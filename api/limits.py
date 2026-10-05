"""Bounded request bodies before multipart/JSON parsing; no payload logging."""
from starlette.responses import JSONResponse
class BodyLimit:
    def __init__(self,app,maximum=11*1024*1024):self.app=app;self.maximum=maximum
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        # Buffer at most the fixed upload limit, reject before route parsing.
        messages=[];size=0
        while True:
            message=await receive()
            if message['type']!='http.request':return
            size+=len(message.get('body',b''))
            if size>self.maximum:
                response=JSONResponse({'error':{'code':'UPLOAD_TOO_LARGE','message':'Request exceeds the upload limit.','request_id':scope.get('state',{}).get('request_id','unavailable')}},status_code=413)
                return await response(scope,receive,send)
            messages.append(message)
            if not message.get('more_body'):break
        index=0
        async def bounded():
            nonlocal index
            if index<len(messages):item=messages[index];index+=1;return item
            return await receive()
        await self.app(scope,bounded,send)
