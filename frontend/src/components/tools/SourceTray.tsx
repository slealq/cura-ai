import LibraryImage from '@/components/LibraryImage';
export interface SourceImage {
  type: 'gallery' | 'generated' | 'upload';
  id?: number;
  key?: string;
  previewUrl?: string;
  fullUrl?: string;
  largeUrl?: string;
  width?: number;
  height?: number;
  name?: string;
  role?: 'reference' | 'element_main' | 'element_angle';
  element?: number;
}

export function sourceLabel(model: string, index: number) {
  if (model === 'kling-image') return `@Image${index + 1}`;
  if (model === 'ideogram-v4.5-edit') return index === 0 ? 'Base' : `Reference ${index}`;
  return `Image ${index + 1}`;
}

interface SourceTrayProps {
  sources: SourceImage[];
  model: string;
  limit: number;
  onChange: (sources: SourceImage[]) => void;
  onAdd: () => void;
  onUpload: (files: FileList) => void;
  onUse: (label: string) => void;
  labels?: string[];
  overLimit?: boolean[];
}

export default function SourceTray({ sources, model, limit, onChange, onAdd, onUpload, onUse, labels, overLimit }: SourceTrayProps) {
  function move(index: number, offset: number) {
    const next = [...sources];
    [next[index], next[index + offset]] = [next[index + offset], next[index]];
    onChange(next);
  }

  const addClass = 'flex min-h-[86px] flex-1 items-center justify-center rounded-md border border-dashed border-input p-3 text-center text-[13px] text-muted-foreground hover:bg-muted focus-within:ring-2 focus-within:ring-ring';

  return (
    <div className="tool-sources flex min-h-[180px] flex-1 flex-wrap items-stretch justify-center gap-2">
      {sources.map((source, index) => (
        <div
          key={`${source.type}-${source.id ?? source.key}-${index}`}
          className={`tool-source group relative min-h-[180px] max-w-[300px] flex-[1_1_180px] overflow-hidden rounded-md bg-muted ${(overLimit?.[index] ?? index >= limit) ? 'opacity-40' : ''}`}
        >
          {source.previewUrl && (
            <LibraryImage src={source.previewUrl} alt={(labels?.[index] ?? sourceLabel(model, index))} className="absolute inset-0 h-full w-full object-cover" />
          )}
          <span className="absolute left-1.5 top-1.5 rounded bg-black/65 px-1.5 py-px font-mono text-[10.5px] text-white">
            {(labels?.[index] ?? sourceLabel(model, index))}
          </span>
          <div className="absolute bottom-1 right-1 flex flex-wrap justify-end gap-[3px] opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100 [&>button]:rounded [&>button]:bg-white/95 [&>button]:px-1.5 [&>button]:py-0.5 [&>button]:text-[11px] [&>button]:text-black [&>button:disabled]:opacity-40">
            <button aria-label={`Move ${(labels?.[index] ?? sourceLabel(model, index))} earlier`} disabled={index === 0} onClick={() => move(index, -1)}>←</button>
            <button aria-label={`Move ${(labels?.[index] ?? sourceLabel(model, index))} later`} disabled={index === sources.length - 1} onClick={() => move(index, 1)}>→</button>
            <button onClick={() => onUse((labels?.[index] ?? sourceLabel(model, index)))}>Use in prompt</button>
            <button onClick={() => onChange(sources.filter((_, i) => i !== index))}>Remove</button>
          </div>
        </div>
      ))}
      <div className="flex w-[120px] shrink-0 flex-col gap-2">
        <button onClick={() => { window.dispatchEvent(new Event('mobile-close-sheets')); onAdd(); }} className={addClass}>+ Add from library</button>
        <label className={`${addClass} relative cursor-pointer`}>
          + Upload
          <input
            type="file"
            aria-label="Upload sources"
            accept="image/*"
            multiple
            className="absolute inset-0 w-full cursor-pointer opacity-0"
            onChange={(event) => {
              if (event.target.files) onUpload(event.target.files);
              event.target.value = '';
            }}
          />
        </label>
      </div>
    </div>
  );
}
