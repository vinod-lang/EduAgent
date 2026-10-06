"use client";
import {useEffect} from "react";
/** No private state persistence. Expiry bypasses warnings and hides protected content. */
export function useUnsavedWork(active:boolean){
 useEffect(()=>{if(!active)return;
  const message="Leave this workspace? Unsaved work may be lost. Download or save it before leaving.";
  const unload=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue="";};
  const click=(e:MouseEvent)=>{const target=e.target instanceof Element?e.target:null;const a=target?.closest('a');if(!a||e.defaultPrevented||a.target==="_blank"||a.hasAttribute('download')||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;const url=new URL(a.href,location.href);if(url.href===location.href||url.pathname===location.pathname&&url.search===location.search)return;if(!window.confirm(message)){e.preventDefault();e.stopPropagation();}};
  const logout=(e:MouseEvent)=>{const target=e.target instanceof Element?e.target.closest('button[aria-label="Sign out"]'):null;if(target&&!window.confirm(message)){e.preventDefault();e.stopPropagation();}};
  window.addEventListener('beforeunload',unload);document.addEventListener('click',click,true);document.addEventListener('click',logout,true);
  return()=>{window.removeEventListener('beforeunload',unload);document.removeEventListener('click',click,true);document.removeEventListener('click',logout,true);};
 },[active]);
}
