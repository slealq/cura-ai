import type { CatalogImageModel } from '@/types';
import type { EditJob } from './JobTabs';
interface ModelPanelProps {
  models: CatalogImageModel[];
  job: EditJob;
  value: string;
  onChange: (key: string) => void;
  children?: React.ReactNode;
}

export default function ModelPanel({ models, job, value, onChange, children }: ModelPanelProps) {
  const offered = models.filter(model => model.jobs.includes(job));
  return (
    <>
      <label className="block text-xs text-muted-foreground">
        Model, {offered.length} can do this
        <select
          className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1.5 text-[13px] text-foreground"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          {offered.map((model) => (
            <option key={model.key} value={model.key}>{model.label}</option>
          ))}
        </select>
      </label>
      {children}
    </>
  );
}
