import { CoursesPage } from '@/features/courses';
import { decodeRouteSegment } from '@/lib/academic';
export default async function Page({params}:{params:Promise<{course:string}>}){const {course}=await params;return <CoursesPage course={decodeRouteSegment(course)}/>;}
