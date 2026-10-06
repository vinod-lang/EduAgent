import { describe,it,expect,vi } from "vitest";
import { APIClient,APIError,parseError } from "@/lib/api";
function reply(value:unknown,status=200){return new Response(JSON.stringify(value),{status,headers:{"Content-Type":"application/json"}});}
describe("safe typed API boundary",()=>{
  it.each([401,403,404,409,422,503,500])("sanitizes %i errors",async(status)=>{const error=await parseError(reply({error:{code:"REQUEST_FAILED",message:"SQL /private/path TOKEN student marks",request_id:"secret"}},status));expect(error).toBeInstanceOf(APIError);expect(error.message).not.toMatch(/SQL|private|TOKEN|marks/);expect(error.requestId).toBeUndefined();});
  it("handles non-JSON errors",async()=>{const error=await parseError(new Response("Traceback SQL",{status:500}));expect(error.message).not.toMatch(/Traceback|SQL/);});
  it("includes credentials and backend CSRF token on mutations",async()=>{const transport=vi.fn().mockResolvedValueOnce(reply({csrf_token:"csrf-one"})).mockResolvedValueOnce(reply({answer:"PCA",grounded:true,sources:[]}));const client=new APIClient(transport);await client.answer({question:"PCA",filters:{}});expect(transport.mock.calls[0][0]).toBe("/api/v1/auth/csrf");expect(transport.mock.calls[1][1]).toMatchObject({credentials:"include",method:"POST",headers:{"X-CSRF-Token":"csrf-one"}});});
  it("uses login token without storing credentials",async()=>{const write=vi.spyOn(Storage.prototype,"setItem");const transport=vi.fn().mockResolvedValueOnce(reply({csrf_token:"login-csrf"})).mockResolvedValueOnce(reply({status:"signed_out"}));const client=new APIClient(transport);await client.login("professor-a");await client.logout();expect(transport.mock.calls[1][1].headers["X-CSRF-Token"]).toBe("login-csrf");expect(write).not.toHaveBeenCalled();});
  it("refreshes a rejected CSRF token once",async()=>{const transport=vi.fn().mockResolvedValueOnce(reply({csrf_token:"old"})).mockResolvedValueOnce(reply({error:{code:"CSRF_REJECTED"}},403)).mockResolvedValueOnce(reply({csrf_token:"new"})).mockResolvedValueOnce(reply({answer:"PCA",grounded:true,sources:[]}));await new APIClient(transport).answer({question:"PCA",filters:{}});expect(transport).toHaveBeenCalledTimes(4);expect(transport.mock.calls[3][1].headers["X-CSRF-Token"]).toBe("new");});
  it("does not automatically repeat failed generation",async()=>{const transport=vi.fn().mockResolvedValueOnce(reply({csrf_token:"csrf"})).mockResolvedValueOnce(reply({error:{code:"PROVIDER_UNAVAILABLE"}},503));await expect(new APIClient(transport).answer({question:"PCA",filters:{}})).rejects.toMatchObject({status:503});expect(transport).toHaveBeenCalledTimes(2);});
  it("signals session expiry",async()=>{const transport=vi.fn().mockResolvedValue(reply({error:{code:"UNAUTHENTICATED"}},401));const client=new APIClient(transport);const expire=vi.fn();client.subscribeUnauthorized(expire);await expect(client.me()).rejects.toMatchObject({status:401});expect(expire).toHaveBeenCalledOnce();});
  it("supports cancellation",async()=>{const controller=new AbortController();const signal=controller.signal;const transport=vi.fn().mockRejectedValue(new DOMException("Cancelled","AbortError"));await expect(new APIClient(transport).me(signal)).rejects.toMatchObject({name:"AbortError"});controller.abort();expect(transport.mock.calls[0][1].signal.aborted).toBe(true);});
  it("maps network failures safely",async()=>{await expect(new APIClient(vi.fn().mockRejectedValue(new Error("private upstream URL"))).me()).rejects.toMatchObject({status:0,code:"NETWORK_ERROR"});});
});

it('retries multipart only after CSRF rejection without setting a JSON content type',async()=>{
 let writes=0;const transport=vi.fn(async(path:RequestInfo|URL,init?:RequestInit)=>{
  if(String(path).endsWith('/auth/csrf'))return new Response(JSON.stringify({csrf_token:`token-${writes}`}));
  expect(init?.method).toBe('POST');writes++;return new Response(JSON.stringify(writes===1?{error:{code:'CSRF_REJECTED'}}:{success:true,duplicate:false,material:null}),{status:writes===1?403:200});
 });const client=new APIClient(transport);await client.upload(new File(['synthetic'],'synthetic.pdf'),{course:'C',semester:'S',subject:'X',unit:'U'});
 expect(writes).toBe(2);const calls=transport.mock.calls.filter(([,init])=>init?.method==='POST');expect(calls[0][1]?.body).toBe(calls[1][1]?.body);expect(calls[1][1]?.headers).not.toHaveProperty('Content-Type');
});

it('does not retry a partial deletion automatically',async()=>{
 const transport=vi.fn(async(path:RequestInfo|URL)=>String(path).endsWith('/auth/csrf')?new Response(JSON.stringify({csrf_token:'synthetic'})):new Response(JSON.stringify({success:false,sqlite_deleted:false,vectors_deleted:2,file_deleted:false})));
 expect((await new APIClient(transport).deleteMaterial('synthetic')).success).toBe(false);expect(transport).toHaveBeenCalledTimes(2);
});

it('normalizes malformed successful JSON without exposing upstream text',async()=>{const client=new APIClient(vi.fn().mockResolvedValue(new Response('PRIVATE INTERNAL',{status:200})));await expect(client.me()).rejects.toMatchObject({code:'INVALID_RESPONSE',status:502});});

it.each([null,'private string',42])('rejects scalar malformed JSON safely: %s',async value=>{await expect(new APIClient(vi.fn().mockResolvedValue(reply(value))).me()).rejects.toMatchObject({code:'INVALID_RESPONSE'});});
