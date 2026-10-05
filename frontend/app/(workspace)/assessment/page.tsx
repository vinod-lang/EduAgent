import {Suspense} from 'react';
import {AssessmentPage} from '@/features/assessment';
export default function Page(){return <Suspense fallback={<p role='status'>Loading Assessment Studio…</p>}><AssessmentPage/></Suspense>;}
