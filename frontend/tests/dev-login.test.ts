// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { POST } from '../app/api/v1/auth/dev-login/route';
beforeEach(()=>{vi.stubEnv('NODE_ENV','development');vi.stubEnv('EDUAGENT_FRONTEND_MODE','development');vi.stubEnv('EDUAGENT_FRONTEND_DEV_AUTH','true');vi.stubEnv('EDUAGENT_DEV_ALIASES','professor-a');vi.stubEnv('EDUAGENT_DEV_ACCESS_KEY','synthetic-test-only');});
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();});
function request(origin='http://127.0.0.1:3000',identity='professor-a'){return new NextRequest('http://localhost:3000/api/v1/auth/dev-login',{method:'POST',headers:{host:'127.0.0.1:3000',origin,'content-type':'application/json'},body:JSON.stringify({identity})});}
describe('server-only development login',()=>{
 it('rejects production even with development flags',async()=>{vi.stubEnv('NODE_ENV','production');expect((await POST(request())).status).toBe(403);});
 it('rejects cross-origin requests',async()=>{expect((await POST(request('http://evil.example'))).status).toBe(403);});
 it('rejects unconfigured identity aliases',async()=>{expect((await POST(request(undefined,'unknown'))).status).toBe(401);});
 it('forwards the secret only to the backend and returns only CSRF and cookie',async()=>{const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({csrf_token:'synthetic-csrf',private:'hidden'}),{headers:{'Set-Cookie':'session=synthetic; HttpOnly; SameSite=Strict'}}));vi.stubGlobal('fetch',fetcher);const result=await POST(request());expect(result.status).toBe(200);expect(await result.json()).toEqual({csrf_token:'synthetic-csrf'});expect(result.headers.get('set-cookie')).toContain('HttpOnly');expect(fetcher.mock.calls[0][1].headers['X-Development-Key']).toBe('synthetic-test-only');});
 it('does not expose backend failures',async()=>{vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('/private/path sensitive backend error')));const response=await POST(request());expect(response.status).toBe(503);expect(await response.text()).not.toContain('sensitive');});
});
