'use client';

import { useState } from 'react';
import LibraryImage from '@/components/LibraryImage';
import MobileSheet from './MobileSheet';
import type { SourceImage } from './SourceTray';

export default function SubjectSlots({ sources, count, onCount, onChange, onAdd }: {
  sources: SourceImage[];
  count: number;
  onCount: (count: number) => void;
  onChange: (sources: SourceImage[]) => void;
  onAdd: () => void;
}) {
  const [slot, setSlot] = useState<{ element: number; role: 'element_main' | 'element_angle'; index?: number }>();
  function assign(index: number) {
    if (!slot) return;
    onChange(sources.map((source, i) => {
      if (i === index) return { ...source, element: slot.element, role: slot.role };
      if (i === slot.index || (slot.role === 'element_main' && source.element === slot.element && source.role === 'element_main')) return { ...source, element: undefined, role: undefined };
      return source;
    }));
    setSlot(undefined);
  }
  return (
    <div className="space-y-4 md:hidden">
      {Array.from({ length: count }, (_, index) => {
        const element = index + 1;
        const main = sources.findIndex(source => source.element === element && source.role === 'element_main');
        const angles = sources.flatMap((source, i) => source.element === element && source.role === 'element_angle' ? [i] : []);
        return (
          <section key={element} className="space-y-2">
            <h2 className="text-sm font-medium">@Element{element}</h2>
            <div className="flex gap-2">
              <button className="relative min-h-44 flex-1 overflow-hidden rounded-md border border-dashed" onClick={() => setSlot({ element, role: 'element_main', index: main })}>
                {sources[main]?.previewUrl ? <LibraryImage src={sources[main].previewUrl!} alt="Main photo" className="absolute inset-0 h-full w-full object-cover" /> : 'Main photo'}
              </button>
              <div className="flex w-24 flex-col gap-2">
                {Array.from({ length: 3 }, (_, angle) => (
                  <button key={angle} className="relative min-h-14 flex-1 overflow-hidden rounded border border-dashed" onClick={() => setSlot({ element, role: 'element_angle', index: angles[angle] })}>
                    {sources[angles[angle]]?.previewUrl ? <LibraryImage src={sources[angles[angle]].previewUrl!} alt={`Angle ${angle + 1}`} className="absolute inset-0 h-full w-full object-cover" /> : '+ Angle'}
                  </button>
                ))}
              </div>
            </div>
          </section>
        );
      })}
      <button className="min-h-10 rounded border px-3" onClick={() => onCount(count + 1)}>+ Subject</button>
      <h2 className="text-sm font-medium">Composition references</h2>
      <div className="flex gap-2 overflow-x-auto">
        {sources.filter(source => !source.element).map((source, index) => (
          <div key={index} className="relative h-24 w-24 shrink-0 overflow-hidden rounded bg-muted">
            {source.previewUrl && <LibraryImage src={source.previewUrl} alt={`@Image${index + 1}`} className="h-full w-full object-cover" />}
            <span className="absolute bottom-0 bg-background/90 px-1 text-xs">@Image{index + 1}</span>
          </div>
        ))}
        <button className="min-h-24 min-w-24 rounded border border-dashed" onClick={onAdd}>+ Reference</button>
      </div>
      {slot && <MobileSheet title={slot.role === 'element_main' ? 'Main photo' : 'Alternate angle'} onClose={() => setSlot(undefined)}>
        <div className="grid grid-cols-3 gap-2">
          {sources.map((source, index) => <button key={index} className="relative aspect-square overflow-hidden rounded bg-muted" onClick={() => assign(index)} aria-label={`Use source ${index + 1}`}>
            {source.previewUrl && <LibraryImage src={source.previewUrl} alt={`Source ${index + 1}`} className="h-full w-full object-cover" />}
          </button>)}
        </div>
        <button className="block min-h-12" onClick={() => { setSlot(undefined); onAdd(); }}>Add from library</button>
        {slot.index != null && slot.index >= 0 && <button className="min-h-10 text-danger" onClick={() => { onChange(sources.map((source, index) => index === slot.index ? { ...source, role: undefined, element: undefined } : source)); setSlot(undefined); }}>Remove from slot</button>}
      </MobileSheet>}
    </div>
  );
}
