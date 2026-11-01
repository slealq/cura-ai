'use client';

import { useRef, useState } from 'react';
import LibraryImage from '@/components/LibraryImage';

export interface Box {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}
export interface ObjectBox {
  label: string;
  description: string;
  action: 'Place' | 'Move' | 'Remove';
  source_box?: Box;
  target_box?: Box;
}

export default function BoxCanvas({ source, boxes, selected, onChange }: {
  source?: string;
  boxes: { label: string; box?: Box }[];
  selected: number;
  onChange: (box: Box) => void;
}) {
  const [dimensions, setDimensions] = useState({ width: 1, height: 1 });
  const gesture = useRef<{ pointer: number; x: number; y: number; box?: Box }>();
  const latestChange = useRef(onChange);
  latestChange.current = onChange;

  function point(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  }

  function update(event: React.PointerEvent<HTMLDivElement>) {
    const start = gesture.current;
    if (!start || event.pointerId !== start.pointer) return;
    const { x, y } = point(event);
    let box: Box;
    if (start.box) {
      const dx = Math.max(-start.box.x_min, Math.min(1 - start.box.x_max, x - start.x));
      const dy = Math.max(-start.box.y_min, Math.min(1 - start.box.y_max, y - start.y));
      box = { x_min: start.box.x_min + dx, x_max: start.box.x_max + dx, y_min: start.box.y_min + dy, y_max: start.box.y_max + dy };
    } else {
      box = { x_min: Math.min(x, start.x), x_max: Math.max(x, start.x), y_min: Math.min(y, start.y), y_max: Math.max(y, start.y) };
    }
    if (box.x_max > box.x_min && box.y_max > box.y_min) latestChange.current(box);
  }

  if (!source) return <p className="text-sm text-muted-foreground">Add a base image to draw boxes.</p>;
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">Drag empty space to draw the selected box. Drag its interior to move it. Draw again to resize.</p>
      <div className="relative mx-auto w-full max-w-[900px]" style={{ aspectRatio: `${dimensions.width}/${dimensions.height}`, width: `min(100%, ${55 * dimensions.width / dimensions.height}vh)` }}>
        <LibraryImage key={source} src={source} alt="Base image for boxes" className="absolute inset-0 h-full w-full" onLoad={event => {
          setDimensions({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight });
        }} />
        <div
          role="application"
          aria-label="Draw or move selected box"
          className="absolute inset-0 touch-none cursor-crosshair"
          onPointerDown={event => {
            if (selected < 0 || event.button !== 0) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            const { x, y } = point(event);
            const box = boxes[selected]?.box;
            const inside = box && x >= box.x_min && x <= box.x_max && y >= box.y_min && y <= box.y_max;
            gesture.current = { pointer: event.pointerId, x, y, box: inside ? { ...box } : undefined };
          }}
          onPointerMove={update}
          onPointerUp={event => {
            update(event);
            gesture.current = undefined;
            event.currentTarget.releasePointerCapture(event.pointerId);
          }}
          onPointerCancel={() => { gesture.current = undefined; }}
          onLostPointerCapture={() => { gesture.current = undefined; }}
        >
          {boxes.map(({ label, box }, index) => box && (
            <div key={index} className={`pointer-events-none absolute border-2 ${index === selected ? 'border-primary bg-primary/15' : 'border-amber-500 bg-amber-500/10'}`} style={{ left: `${box.x_min * 100}%`, top: `${box.y_min * 100}%`, width: `${(box.x_max - box.x_min) * 100}%`, height: `${(box.y_max - box.y_min) * 100}%` }}>
              <span className="absolute left-0 top-0 max-w-full truncate bg-background/90 px-1 text-xs">{label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
