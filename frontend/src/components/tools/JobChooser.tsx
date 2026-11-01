import { jobs, type EditJob } from './JobTabs';

export default function JobChooser({ value, onChange }: { value?: EditJob; onChange: (job: EditJob) => void }) {
  return (
    <>
      <h2 className="font-semibold">What do you want to do?</h2>
      {(Object.keys(jobs) as EditJob[]).map(job => (
        <button key={job} aria-pressed={value === job} className="block min-h-12 w-full text-left" onClick={() => onChange(job)}>{jobs[job]}</button>
      ))}
    </>
  );
}
