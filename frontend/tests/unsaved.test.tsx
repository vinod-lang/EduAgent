import React from 'react';
import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent} from '@testing-library/react';
import {useUnsavedWork} from '@/features/use-unsaved-work';
function Probe({active=true}:{active?:boolean}){useUnsavedWork(active);return <><a href="/home">Home</a><button aria-label="Sign out">Logout</button></>;}
it('warns before leaving unsaved work, without persisting it',()=>{const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);render(<Probe/>);expect(fireEvent.click(screen.getByRole('link'))).toBe(false);expect(confirm).toHaveBeenCalledOnce();});
it('warns before sign out while preserving professor choice',()=>{const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);render(<Probe/>);expect(fireEvent.click(screen.getByRole('button'))).toBe(false);expect(confirm).toHaveBeenCalledOnce();});
it('installs and cleans beforeunload only for unsaved work',()=>{const view=render(<Probe/>);const e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);expect(e.defaultPrevented).toBe(true);view.rerender(<Probe active={false}/>);const after=new Event('beforeunload',{cancelable:true});window.dispatchEvent(after);expect(after.defaultPrevented).toBe(false);});
