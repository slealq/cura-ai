'use client';

import { useEffect, useState } from 'react';
import MobileSheet from './MobileSheet';
import JobChooser from './JobChooser';

export type EditJob = 'describe' | 'paint' | 'objects' | 'subject';
export const jobs: Record<EditJob, string> = {
  describe: 'Describe the change',
  paint: 'Paint an area',
  objects: 'Arrange objects',
  subject: 'Keep a subject',
};

export default function JobTabs({ value, onChange }: { value: EditJob; onChange: (job: EditJob) => void }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener('mobile-edit-jobs', show);
    // Deferred so the layout's listener, which mounts after this child, hears it on a hard load.
    const title = setTimeout(() => window.dispatchEvent(new CustomEvent('mobile-edit-title', { detail: jobs[value] })), 0);
    return () => { clearTimeout(title); window.removeEventListener('mobile-edit-jobs', show); };
  }, [value]);
  return (
    <>
    <div role="group" aria-label="Job" className="inline-flex max-w-full gap-0.5 overflow-x-auto rounded-[7px] bg-muted p-0.5">
      {(Object.keys(jobs) as EditJob[]).map((job) => (
        <button
          key={job}
          aria-pressed={job === value}
          onClick={() => onChange(job)}
          className="whitespace-nowrap rounded-[5px] px-[11px] py-[5px] text-[13px] text-muted-foreground aria-pressed:bg-background aria-pressed:font-medium aria-pressed:text-foreground aria-pressed:shadow-sm"
        >
          {jobs[job]}
        </button>
      ))}
    </div>
    {open && <MobileSheet title="Edit" onClose={() => setOpen(false)}><JobChooser value={value} onChange={job => { onChange(job); setOpen(false); }} /></MobileSheet>}
    </>
  );
}
