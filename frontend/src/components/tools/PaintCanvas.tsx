'use client';

import { useEffect, useRef, useState } from 'react';
import LibraryImage from '@/components/LibraryImage';
import type { Box } from './BoxCanvas';

const PAINT_COLOR = 'hsl(225 80% 55%)';

export interface PaintMask {
  dataUrl: string;
  percent: number;
}

export default function PaintCanvas({ source, value, onChange, region }: {
  source?: string;
  region?: Box;
  value?: PaintMask;
  onChange: (value: PaintMask) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const undo = useRef<ImageData[]>([]);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ distance: number; x: number; y: number; scale: number; tx: number; ty: number }>();
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const drawing = useRef(false);
  const last = useRef<{ x: number; y: number } | null>(null);
  const [size, setSize] = useState(40);
  const [erase, setErase] = useState(false);
  const [visible, setVisible] = useState(true);
  const [dimensions, setDimensions] = useState({ width: 1, height: 1 });

  useEffect(() => {
    const context = canvas.current?.getContext('2d');
    if (!context) return;
    context.clearRect(0, 0, dimensions.width, dimensions.height);
    if (!value?.dataUrl) return;
    let active = true;
    const image = new Image();
    image.onload = () => {
      if (!active) return;
      context.globalCompositeOperation = 'source-over';
      context.drawImage(image, 0, 0);
    };
    image.src = value.dataUrl;
    return () => { active = false; };
  }, [source, dimensions, value?.dataUrl]);

  useEffect(() => {
    undo.current = [];
    pointers.current.clear();
    pinch.current = undefined;
    setView({ scale: 1, x: 0, y: 0 });
  }, [source]);

  function restoreStroke() {
    const previous = undo.current.pop();
    if (previous) canvas.current?.getContext('2d')?.putImageData(previous, 0, 0);
  }

  function finish(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.delete(event.pointerId);
    drawing.current = false;
    last.current = null;
    if (!pointers.current.size) { pinch.current = undefined; save(); }
  }

  function save() {
    const node = canvas.current;
    const context = node?.getContext('2d');
    if (!node || !context) return;
    const pixels = context.getImageData(0, 0, node.width, node.height);
    let selected = 0;
    for (let i = 3; i < pixels.data.length; i += 4) {
      if (pixels.data[i] >= 128) selected++;
    }
    onChange({ dataUrl: node.toDataURL('image/png'), percent: selected / (node.width * node.height) * 100 });
  }

  function paint(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current || !canvas.current) return;
    const node = canvas.current;
    const rect = node.getBoundingClientRect();
    const point = { x: (event.clientX - rect.left) * node.width / rect.width, y: (event.clientY - rect.top) * node.height / rect.height };
    const context = node.getContext('2d')!;
    context.globalCompositeOperation = erase ? 'destination-out' : 'source-over';
    context.strokeStyle = PAINT_COLOR;
    context.fillStyle = PAINT_COLOR;
    const radius = size * node.width / rect.width / 2;
    context.lineWidth = radius * 2;
    context.lineCap = 'round';
    context.beginPath();
    context.moveTo(last.current?.x ?? point.x, last.current?.y ?? point.y);
    context.lineTo(point.x, point.y);
    context.stroke();
    context.beginPath();
    context.arc(point.x, point.y, radius, 0, Math.PI * 2);
    context.fill();
    last.current = point;
  }

  return (
    <div className="flex min-h-[240px] flex-1 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <div role="group" aria-label="Brush" className="inline-flex gap-0.5 rounded-md bg-muted p-0.5">
          {[false, true].map(mode => (
            <button
              key={String(mode)}
              aria-pressed={erase === mode}
              onClick={() => setErase(mode)}
              className={`rounded px-2.5 py-1 ${erase === mode ? 'bg-background font-medium text-foreground shadow-sm' : 'text-muted-foreground'}`}
            >
              {mode ? 'Erase' : 'Brush'}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2">Size
          <input aria-label="Brush size" type="range" min="2" max="160" value={size} onChange={event => setSize(Number(event.target.value))} />
          {size}px
        </label>
        <button className="rounded-md border border-border px-2 py-1 text-muted-foreground hover:bg-muted" onClick={() => {
          const node = canvas.current;
          if (node) undo.current.push(node.getContext('2d')!.getImageData(0, 0, node.width, node.height));
          canvas.current?.getContext('2d')?.clearRect(0, 0, dimensions.width, dimensions.height);
          save();
        }}>Clear</button>
        <button className="rounded-md border border-border px-2 py-1 text-muted-foreground hover:bg-muted" aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? 'Hide' : 'Show'} area</button>
        <button className="rounded-md border border-border px-2 py-1 text-muted-foreground md:hidden" onClick={() => { restoreStroke(); save(); }}>Undo</button>
        <span className="font-mono">{(value?.percent ?? 0).toFixed(1)}% selected</span>
      </div>
      {source ? (
        <div className="paint-viewport min-h-0 flex-1 overflow-hidden">
        <div className="paint-image relative mx-auto w-full max-w-[900px]" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`, '--paint-ratio': dimensions.width / dimensions.height, aspectRatio: `${dimensions.width}/${dimensions.height}`, width: `min(100%, ${55 * dimensions.width / dimensions.height}vh)` } as React.CSSProperties}>
          <LibraryImage src={source} alt="Base image to paint" className="absolute inset-0 h-full w-full" onLoad={event => {
            const image = event.currentTarget;
            setDimensions({ width: image.naturalWidth, height: image.naturalHeight });
          }} />
          {region && (
            <div className="pointer-events-none absolute z-10 border-2 border-primary" style={{ left: `${region.x_min * 100}%`, top: `${region.y_min * 100}%`, width: `${(region.x_max - region.x_min) * 100}%`, height: `${(region.y_max - region.y_min) * 100}%` }}>
              <span className="bg-background/90 px-1 text-xs">Precision area</span>
            </div>
          )}
          <canvas
            ref={canvas}
            width={dimensions.width}
            height={dimensions.height}
            aria-label="Paint the area to change"
            className="absolute inset-0 h-full w-full touch-none cursor-crosshair"
            style={{ opacity: visible ? 0.5 : 0, pointerEvents: visible ? 'auto' : 'none' }}
            onPointerDown={event => {
              if (event.button !== 0) return;
              event.currentTarget.setPointerCapture(event.pointerId);
              pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
              if (window.matchMedia('(max-width: 767px)').matches && pointers.current.size > 1) {
                if (drawing.current) restoreStroke();
                drawing.current = false;
                last.current = null;
                const [a, b] = Array.from(pointers.current.values());
                pinch.current = { distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, scale: view.scale, tx: view.x, ty: view.y };
                return;
              }
              if (pinch.current) return;
              const node = canvas.current;
              if (node) {
                undo.current.push(node.getContext('2d')!.getImageData(0, 0, node.width, node.height));
                if (undo.current.length > 12) undo.current.shift();
              }
              drawing.current = true;
              last.current = null;
              paint(event);
            }}
            onPointerMove={event => {
              if (!pointers.current.has(event.pointerId)) return;
              pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
              const start = pinch.current;
              if (start && pointers.current.size >= 2) {
                const [a, b] = Array.from(pointers.current.values());
                setView({ scale: Math.max(1, Math.min(6, start.scale * Math.hypot(a.x - b.x, a.y - b.y) / start.distance)), x: start.tx + (a.x + b.x) / 2 - start.x, y: start.ty + (a.y + b.y) / 2 - start.y });
              } else if (!start) paint(event);
            }}
            onPointerUp={finish}
            onPointerCancel={finish}
            onLostPointerCapture={finish}
          />
        </div>
        </div>
      ) : <p className="text-sm text-muted-foreground">Add a base image, then paint the area to change.</p>}
    </div>
  );
}

export async function maskFile(mask: PaintMask): Promise<File> {
  const image = new Image();
  image.src = mask.dataUrl;
  await image.decode();
  const canvas = document.createElement('canvas');
  canvas.width = image.width;
  canvas.height = image.height;
  const context = canvas.getContext('2d')!;
  // Canonical mask: white edits, black preserves, whatever color the strokes show in.
  context.drawImage(image, 0, 0);
  context.globalCompositeOperation = 'source-in';
  context.fillStyle = 'white';
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.globalCompositeOperation = 'destination-over';
  context.fillStyle = 'black';
  context.fillRect(0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error('Could not export mask')), 'image/png'));
  return new File([blob], 'paint-mask.png', { type: 'image/png' });
}
