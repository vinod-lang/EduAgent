import React from 'react';
import {it,expect,vi} from 'vitest';
import {render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import {APIClient} from '@/lib/api';
import {AuthProvider} from '@/features/auth';
import {ActivityPage} from '@/features/activity';
import {DashboardPage} from '@/features/dashboard';
vi.mock('next/navigation',()=>({usePathname:()=>'/activity',useRouter:()=>({replace:vi.fn()})}));
vi.mock('next/link',()=>({default:({href,children,...p}:{href:string}&React.ComponentProps<'a'>)=><a href={href} {...p}>{children}</a>}));
function mount(o:{empty?:boolean;status?:number;dashboard?:boolean}={}){const transport=vi.fn(async(input:RequestInfo|URL)=>{const path=String(input);let data:unknown={};let status=200;
if(path.endsWith('/auth/me'))data={professor_id:'synthetic',display_name:'Synthetic Professor',institution_id:'synthetic',department_id:'synthetic'};
else if(path.endsWith('/dashboard'))data={material_count:0,courses:[],materials:[],saved_drafts:[],activity:[]};
else if(path.endsWith('/system/ai'))data={preferred_model:'qwen2.5:3b'};
else{status=o.status??200;const query=new URL(path,'http://frontend.test').searchParams;data={items:o.empty||query.get('category')==='Documents'?[]:query.has('before')?[{action:'Recorded activity',timestamp:'Time unavailable',category:'Workspace',private_details:'NEVER RENDER student /private'}]:[{action:'Material uploaded',timestamp:'2026-10-06T10:00:00Z',category:'Materials'},{action:'Document saved',timestamp:'2026-10-05T10:00:00Z',category:'Documents'}],next_cursor:query.has('before')?null:10};}
if(status!==200)data={error:{code:'ACCESS_DENIED',message:'RAW student private'}};return new Response(JSON.stringify(data),{status});});const client=new APIClient(transport);return {...render(<AuthProvider api={client}>{o.dashboard?<DashboardPage/>:<ActivityPage/>}</AuthProvider>),transport};}
it('shows genuine empty state',async()=>{mount({empty:true});await screen.findByText('No recent activity yet');});
it('renders safe labels and timestamp order',async()=>{mount();await screen.findByText('Material uploaded');const items=screen.getAllByRole('listitem');expect(items[0]).toHaveTextContent('Material uploaded');expect(items[1]).toHaveTextContent('Document saved');expect(screen.getByText(/not every interaction/)).toBeInTheDocument();});
it('filters and resets cursor',async()=>{const {transport}=mount();await screen.findByText('Material uploaded');await userEvent.selectOptions(screen.getByLabelText('Activity category'),'Documents');await screen.findByText('No recent activity yet');expect(transport.mock.calls.at(-1)?.[0]).toContain('category=Documents');});
it('uses cursor pagination and never renders extra private fields',async()=>{mount();await screen.findByText('Material uploaded');await userEvent.click(screen.getByRole('button',{name:'Older activity'}));await screen.findByText('Recorded activity');expect(screen.getByText('Time unavailable')).toBeInTheDocument();expect(screen.queryByText(/NEVER RENDER/)).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'Older activity'})).toBeDisabled();await userEvent.click(screen.getByRole('button',{name:'Newer activity'}));await screen.findByText('Material uploaded');});
it.each([401,403,503])('safe activity HTTP %s',async(status)=>{mount({status});await screen.findByRole('alert');expect(screen.queryByText(/RAW student/)).not.toBeInTheDocument();});
it('Home links to full actor-scoped Activity Center',async()=>{mount({dashboard:true});await screen.findByRole('link',{name:'View all activity'});expect(screen.getByRole('link',{name:'View all activity'})).toHaveAttribute('href','/activity');expect(screen.getByRole('link',{name:'Smart Assistant'})).toHaveAttribute('href','/assistant');});
it('provides semantic accessible activity controls',async()=>{const {container}=mount();await screen.findByText('Material uploaded');const result=await axe.run(container,{rules:{'color-contrast':{enabled:false},region:{enabled:false}}});expect(result.violations).toEqual([]);});
