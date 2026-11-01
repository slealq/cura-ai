'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import LibraryImage from '@/components/LibraryImage';
import MobileSheet from './MobileSheet';
import type { SourceImage } from './SourceTray';

export type SubjectSlot = { element: number; role: NonNullable<SourceImage['role']> };

interface SubjectStageProps {
  sources: SourceImage[];
  count: number;
  onCount: (count: number) => void;
  onChange: (sources: SourceImage[]) => void;
  onPick: (slot: SubjectSlot) => void;
  onUpload: (files: FileList, slot: SubjectSlot) => void;
  onUse: (label: string) => void;
}

interface FitItem {
  key: string;
  ratio: number;
  node: ReactNode;
}

const EMPTY_RATIO = 0.75;
const GAP = 6;

function useBox<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setBox({ w: entry.contentRect.width, h: entry.contentRect.height }));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, box] as const;
}

function ratioOf(source?: SourceImage) {
  return source?.width && source.height ? source.width / source.height : EMPTY_RATIO;
}

// One line of frames, each shaped like its photo, sized so the whole line fits.
function FitRow({ items }: { items: FitItem[] }) {
  const [ref, box] = useBox<HTMLDivElement>();
  const total = items.reduce((sum, item) => sum + item.ratio, 0);
  const height = Math.max(0, Math.min(box.h, (box.w - GAP * (items.length - 1)) / total));
  return (
    <div ref={ref} className="flex h-[150px] min-h-0 min-w-0 gap-1.5 md:h-auto md:flex-1">
      {items.map(item => (
        <div key={item.key} className="relative flex-none" style={{ width: height * item.ratio, height }}>{item.node}</div>
      ))}
    </div>
  );
}

// A subject row: the main photo takes the height, up to 45% of the width.
function SubjectRow({ ratio, main, className, children }: { ratio: number; main: ReactNode; className: string; children: ReactNode }) {
  const [ref, box] = useBox<HTMLElement>();
  const width = box.w < 640 ? Math.min(box.w, 440 * ratio) : Math.min(box.h * ratio, box.w * 0.45);
  return (
    <section ref={ref} className={`flex shrink-0 flex-col gap-3 md:flex-row ${className}`}>
      <div className="relative flex-none" style={{ width, height: width / ratio }}>{main}</div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-1.5">{children}</div>
    </section>
  );
}

export default function SubjectStage({ sources, count, onCount, onChange, onPick, onUpload, onUse }: SubjectStageProps) {
  const [sheet, setSheet] = useState<{ source: SourceImage; label: string; reference: boolean } | null>(null);
  const references = sources.filter(source => !source.role || source.role === 'reference');
  const elements = Array.from({ length: count }, (_, i) => i + 1);
  const emptyMain = elements.find(element => !sources.some(source => source.element === element && source.role === 'element_main'));
  const emptyAngle = elements.find(element => sources.filter(source => source.element === element && source.role === 'element_angle').length < 3);
  const addClass = 'h-full w-full rounded-md border border-dashed border-input text-xs text-muted-foreground hover:bg-muted disabled:opacity-40';

  function assign(source: SourceImage, element: number, role: SubjectSlot['role']) {
    onChange(sources.map(item => item === source ? { ...item, element, role } : item));
  }

  function actions(source: SourceImage, label: string, reference: boolean) {
    return [
      ...(reference && emptyMain != null ? [{ label: 'Use as main', run: () => assign(source, emptyMain, 'element_main') }] : []),
      ...(reference && emptyAngle != null ? [{ label: 'Use as angle', run: () => assign(source, emptyAngle, 'element_angle') }] : []),
      { label: 'Use in prompt', run: () => onUse(label) },
      { label: 'Remove', run: () => onChange(sources.filter(item => item !== source)) },
    ];
  }

  function tile(source: SourceImage, label: string, { tag, main = false, reference = false, over = false }: { tag?: string; main?: boolean; reference?: boolean; over?: boolean }) {
    const src = main
      ? source.fullUrl ?? source.largeUrl ?? source.previewUrl
      : source.largeUrl ?? source.fullUrl ?? source.previewUrl;
    return (
      <div className={`group relative h-full w-full overflow-hidden rounded-md bg-muted ${over ? 'opacity-40' : ''}`}>
        {src && <LibraryImage src={src} alt={label} className="absolute inset-0 h-full w-full object-cover" />}
        {tag && (
          <span className="absolute left-1.5 top-1.5 rounded bg-black/65 px-1.5 py-px font-mono text-[10.5px] text-white">{tag}</span>
        )}
        <button aria-label={`Options for ${label}`} className="absolute inset-0 md:hidden" onClick={() => setSheet({ source, label, reference })} />
        <div className="absolute bottom-1 right-1 hidden flex-wrap justify-end gap-[3px] opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 md:flex [&>button]:rounded [&>button]:bg-white/95 [&>button]:px-1.5 [&>button]:py-0.5 [&>button]:text-[11px] [&>button]:text-black">
          {actions(source, label, reference).map(action => (
            <button key={action.label} onClick={action.run}>{action.label}</button>
          ))}
        </div>
      </div>
    );
  }

  function emptyItem(key: string, label: string, onClick: () => void, disabled = false): FitItem {
    return { key, ratio: EMPTY_RATIO, node: <button className={addClass} disabled={disabled} onClick={onClick}>{label}</button> };
  }

  return (
    <div className="flex shrink-0 flex-col gap-2 md:min-h-0 md:flex-1 md:shrink">
      {elements.map(element => {
        const main = sources.find(source => source.element === element && source.role === 'element_main');
        const angles = sources.filter(source => source.element === element && source.role === 'element_angle');
        const mainSlot: SubjectSlot = { element, role: 'element_main' };
        const label = `@Element${element}`;
        return (
          <SubjectRow
            key={element}
            ratio={ratioOf(main)}
            className={element > 1 ? 'md:h-[240px]' : count > 1 ? 'md:h-[420px]' : 'md:min-h-[360px] md:flex-1'}
            main={main ? tile(main, label, { tag: `${label} · main`, main: true }) : (
              <div className={`${addClass} flex flex-col items-center justify-center`}>
                <button className="min-h-11 px-3" onClick={() => onPick(mainSlot)}>+ Add main photo</button>
                <label className="relative flex min-h-11 cursor-pointer items-center px-3 text-xs">
                  Upload
                  <input type="file" accept="image/*" aria-label={`Upload ${label} main photo`} className="absolute inset-0 w-full cursor-pointer opacity-0" onChange={event => {
                    if (event.target.files) onUpload(event.target.files, mainSlot);
                    event.target.value = '';
                  }} />
                </label>
              </div>
            )}
          >
            <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>{label} · other angles, up to 3</span>
              {element === count && count > 1 && (
                <button className="min-h-11 md:min-h-0" onClick={() => {
                  onChange(sources.filter(source => source.element !== element));
                  onCount(count - 1);
                }}>Remove subject</button>
              )}
            </div>
            <FitRow items={[
              ...angles.map(source => ({ key: `angle-${sources.indexOf(source)}`, ratio: ratioOf(source), node: tile(source, label, {}) })),
              ...Array.from({ length: 3 - angles.length }, (_, i) => emptyItem(`empty-${i}`, '+ Add angle', () => onPick({ element, role: 'element_angle' }))),
            ]} />
            {element === 1 && (
              <>
                <p className="pt-1 text-xs text-muted-foreground">Composition references</p>
                <FitRow items={[
                  ...references.map((source, i) => ({ key: `reference-${sources.indexOf(source)}`, ratio: ratioOf(source), node: tile(source, `@Image${i + 1}`, { tag: `@Image${i + 1}`, reference: true, over: i >= 10 }) })),
                  emptyItem('add-reference', '+ Add reference', () => onPick({ element: 1, role: 'reference' }), references.length >= 10),
                  emptyItem('add-subject', `+ Add @Element${count + 1}`, () => onCount(count + 1)),
                ]} />
              </>
            )}
          </SubjectRow>
        );
      })}
      <p className="shrink-0 text-xs text-muted-foreground">Use a clear frontal main photo. Each image needs sides of at least 300px, aspect 0.4 to 2.5, up to 10 MiB.</p>
      {sheet && (
        <MobileSheet title={sheet.label} onClose={() => setSheet(null)}>
          {actions(sheet.source, sheet.label, sheet.reference).map(action => (
            <button key={action.label} className="block min-h-12 w-full text-left" onClick={() => { action.run(); setSheet(null); }}>{action.label}</button>
          ))}
        </MobileSheet>
      )}
    </div>
  );
}
