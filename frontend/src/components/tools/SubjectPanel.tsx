import LibraryImage from '@/components/LibraryImage';
import { SourceImage } from './SourceTray';

interface SubjectPanelProps {
  sources: SourceImage[];
  count: number;
  onCount: (count: number) => void;
  onChange: (sources: SourceImage[]) => void;
  onUse: (label: string) => void;
}

export default function SubjectPanel({ sources, count, onCount, onChange, onUse }: SubjectPanelProps) {
  function assign(index: number, element: number, role: 'element_main' | 'element_angle') {
    onChange(sources.map((source, i) => {
      if (i === index) return { ...source, element, role };
      if (role === 'element_main' && source.element === element && source.role === role) {
        return { ...source, role: undefined, element: undefined };
      }
      return source;
    }));
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">Add photos using the source tray, then assign a frontal main photo and up to 3 alternate angles per subject. Unassigned photos are composition references (@ImageN). Each image needs sides ≥300px, aspect 0.4–2.5 and size ≤10 MiB.</p>
      {Array.from({ length: count }, (_, index) => {
        const element = index + 1;
        const main = sources.find(source => source.element === element && source.role === 'element_main');
        const angles = sources.filter(source => source.element === element && source.role === 'element_angle');
        return (
          <div key={element} className="space-y-2 rounded-md border border-border p-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium">@Element{element}</span>
              <button className="text-xs text-primary" onClick={() => onUse(`@Element${element}`)}>Use in prompt</button>
            </div>
            {main?.previewUrl && <LibraryImage src={main.previewUrl} alt={`@Element${element} main`} className="h-24 w-full rounded object-cover" />}
            <label className="block text-xs">Frontal main photo
              <select className="mt-1 w-full rounded border border-input bg-background p-1.5" value={main ? sources.indexOf(main) : ''} onChange={event => assign(Number(event.target.value), element, 'element_main')}>
                <option value="" disabled>Select a source</option>
                {sources.map((source, i) => <option key={i} value={i}>Source {i + 1}{source.name ? ` · ${source.name}` : ''}</option>)}
              </select>
            </label>
            <p className="text-xs">Alternate angles ({angles.length}/3)</p>
            <div className="flex flex-wrap gap-1">
              {sources.map((source, i) => {
                if (source === main) return null;
                const selected = angles.includes(source);
                return (
                  <button key={i} aria-pressed={selected} disabled={!selected && angles.length >= 3} className={`rounded border p-1 text-xs disabled:opacity-40 ${selected ? 'border-primary bg-primary/10' : 'border-border'}`} onClick={() => selected ? onChange(sources.map((item, j) => j === i ? { ...item, role: undefined, element: undefined } : item)) : assign(i, element, 'element_angle')}>
                    {source.previewUrl && <LibraryImage src={source.previewUrl} alt="" className="h-10 w-10 rounded object-cover" />}
                    Source {i + 1}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
      <button className="rounded border border-border px-2 py-1 text-xs" onClick={() => onCount(count + 1)}>+ Add subject</button>
      {count > 0 && (
        <button className="ml-2 text-xs text-muted-foreground" onClick={() => {
          onChange(sources.map(source => source.element === count ? { ...source, role: undefined, element: undefined } : source));
          onCount(count - 1);
        }}>Remove last subject</button>
      )}
    </div>
  );
}
