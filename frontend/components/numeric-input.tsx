'use client';
import {useEffect,useRef,useState} from 'react';
import type {InputHTMLAttributes} from 'react';
type Props=Omit<InputHTMLAttributes<HTMLInputElement>,'value'|'onChange'|'type'> & {value:number;onValueChange:(value:number)=>void};
/** Preserve an empty typing buffer; commit numeric semantics without a leading zero. */
export function NumericInput({value,onValueChange,onFocus,onBlur,...props}:Props){
 const [text,setText]=useState(String(value));const submitted=useRef(value);
 useEffect(()=>{if(value!==submitted.current){submitted.current=value;setText(String(value));}},[value]);
 return <input {...props} type="number" value={text} onFocus={e=>{if(text==='0')setText('');onFocus?.(e);}} onChange={e=>{setText(e.target.value);submitted.current=Number(e.target.value);onValueChange(submitted.current);}} onBlur={e=>{setText(String(value));onBlur?.(e);}}/>;
}
