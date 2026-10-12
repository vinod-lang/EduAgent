import {useState} from 'react';
import {it,expect} from 'vitest';
import {render,screen,fireEvent} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {NumericInput} from '@/components/numeric-input';
function Form(){const [value,setValue]=useState(0);return <><label>Count<NumericInput value={value} onValueChange={setValue} min={0} step={1}/></label><output>{value}</output><button>Blur</button></>;}
it.each(['5','10'])('types %s from zero without a leading zero',async text=>{render(<Form/>);const input=screen.getByRole('spinbutton');await userEvent.click(input);await userEvent.type(input,text);expect((input as HTMLInputElement).value).toBe(text);});
it('allows clearing, replacing, valid zero and native arrow/change events',async()=>{render(<Form/>);const input=screen.getByRole('spinbutton');await userEvent.click(input);await userEvent.type(input,'10');await userEvent.clear(input);expect((input as HTMLInputElement).value).toBe('');await userEvent.type(input,'5');expect(input).toHaveValue(5);await userEvent.clear(input);await userEvent.type(input,'0');await userEvent.click(screen.getByRole('button'));expect(input).toHaveValue(0);fireEvent.change(input,{target:{value:'1'}});expect(input).toHaveValue(1);});
