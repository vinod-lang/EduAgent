import { Suspense } from 'react';
import { LibraryPage } from '@/features/library';
export default function Page(){return <Suspense fallback={<p role='status'>Loading library…</p>}><LibraryPage/></Suspense>;}
