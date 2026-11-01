'use client';

import { useState } from 'react';
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

export default function SubjectStage({ sources, count, onCount, onChange, onPick, onUpload, onUse }: SubjectStageProps) {
  const [sheet, setSheet] = useState<{ source: SourceImage; label: string; reference: boolean } | null>(null);
  const references = sources.filter(source => !source.role || source.role === 'reference');
  const elements = Array.from({ length: count }, (_, i) => i + 1);
  const emptyMain = elements.find(element => !sources.some(source => source.element === element && source.role === 'element_main'));
  const emptyAngle = elements.find(element => sources.filter(source => source.element === element && source.role === 'element_angle').length < 3);
  const addClass = 'min-h-11 rounded-md border border-dashed border-input text-xs text-muted-foreground hover:bg-muted';

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

  function tile(source: SourceImage, label: string, reference = false, main = false, over = false) {
    return (
      <div key={sources.indexOf(source)} className={`group relative min-h-0 overflow-hidden rounded-md bg-muted ${main ? 'min-h-44 flex-1 md:min-h-0' : 'aspect-square md:aspect-auto'} ${over ? 'opacity-40' : ''}`}>
        {source.previewUrl && (
          <LibraryImage src={source.previewUrl} alt={label} className="absolute inset-0 h-full w-full object-cover" />
        )}
        {reference && (
          <span className="absolute left-1.5 top-1.5 rounded bg-black/65 px-1.5 py-px font-mono text-[10.5px] text-white">{label}</span>
        )}
        <button aria-label={`Options for ${label}`} className="absolute inset-0 md:hidden" onClick={() => setSheet({ source, label, reference })} />
        <div className="absolute bottom-1 right-1 hidden flex-wrap justify-end gap-[3px] opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 md:flex [@media(hover:none)]:opacity-100 [&>button]:rounded [&>button]:bg-white/95 [&>button]:px-1.5 [&>button]:py-0.5 [&>button]:text-[11px] [&>button]:text-black">
          {actions(source, label, reference).map(action => (
            <button key={action.label} onClick={action.run}>{action.label}</button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex shrink-0 flex-col gap-2 md:min-h-0 md:flex-1 md:shrink">
      {elements.map(element => {
        const main = sources.find(source => source.element === element && source.role === 'element_main');
        const angles = sources.filter(source => source.element === element && source.role === 'element_angle');
        const mainSlot: SubjectSlot = { element, role: 'element_main' };
        return (
          <section key={element} className={`grid shrink-0 grid-cols-1 gap-2 md:grid-cols-[minmax(0,1.3fr)_minmax(0,2fr)] ${element > 1 ? 'md:h-[240px]' : count > 1 ? 'md:h-[420px]' : 'md:min-h-[360px] md:flex-1'}`}>
            <div className="flex min-h-0 flex-col gap-1">
              <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>@Element{element} · main photo</span>
                {element === count && count > 1 && (
                  <button className="min-h-11 md:min-h-0" onClick={() => {
                    onChange(sources.filter(source => source.element !== element));
                    onCount(count - 1);
                  }}>Remove subject</button>
                )}
              </div>
              {main ? tile(main, `@Element${element}`, false, true) : (
                <div className={`${addClass} flex min-h-44 flex-1 flex-col items-center justify-center md:min-h-0`}>
                  <button className="min-h-11 px-3" onClick={() => onPick(mainSlot)}>+ Add main photo</button>
                  <label className="relative flex min-h-11 cursor-pointer items-center px-3 text-xs">
                    Upload
                    <input type="file" accept="image/*" aria-label={`Upload @Element${element} main photo`} className="absolute inset-0 w-full cursor-pointer opacity-0" onChange={event => {
                      if (event.target.files) onUpload(event.target.files, mainSlot);
                      event.target.value = '';
                    }} />
                  </label>
                </div>
              )}
            </div>
            <div className={`grid min-h-0 gap-2 ${element === 1 ? 'md:grid-rows-2' : 'md:grid-rows-1'}`}>
              <div className="flex min-h-0 flex-col gap-1">
                <p className="text-xs text-muted-foreground">@Element{element} · other angles, up to 3</p>
                <div className="grid min-h-0 flex-1 grid-cols-3 gap-1.5">
                  {angles.map(source => tile(source, `@Element${element}`))}
                  {Array.from({ length: 3 - angles.length }, (_, i) => (
                    <button key={`empty-${i}`} className={`${addClass} aspect-square md:aspect-auto`} onClick={() => onPick({ element, role: 'element_angle' })}>+ Add angle</button>
                  ))}
                </div>
              </div>
              {element === 1 && (
                <div className="flex min-h-0 flex-col gap-1">
                  <p className="text-xs text-muted-foreground">Composition references</p>
                  <div className="grid min-h-0 flex-1 auto-rows-max grid-cols-3 gap-1.5 overflow-y-auto md:auto-rows-[minmax(80px,1fr)]">
                    {references.map((source, i) => tile(source, `@Image${i + 1}`, true, false, i >= 10))}
                    <button className={`${addClass} aspect-square md:aspect-auto`} disabled={references.length >= 10} onClick={() => onPick({ element: 1, role: 'reference' })}>+ Add reference</button>
                    <button className={`${addClass} aspect-square md:aspect-auto`} onClick={() => onCount(count + 1)}>+ Add @Element{count + 1}</button>
                  </div>
                </div>
              )}
            </div>
          </section>
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
