export type EditJob = 'describe' | 'paint' | 'objects' | 'subject';
export const jobs: Record<EditJob, string> = {
  describe: 'Describe the change',
  paint: 'Paint an area',
  objects: 'Arrange objects',
  subject: 'Keep a subject',
};

export default function JobTabs({ value, onChange }: { value: EditJob; onChange: (job: EditJob) => void }) {
  return (
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
  );
}
