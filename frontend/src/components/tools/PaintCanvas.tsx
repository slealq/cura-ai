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
          canvas.current?.getContext('2d')?.clearRect(0, 0, dimensions.width, dimensions.height);
          save();
        }}>Clear</button>
        <button className="rounded-md border border-border px-2 py-1 text-muted-foreground hover:bg-muted" aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? 'Hide' : 'Show'} area</button>
        <span className="font-mono">{(value?.percent ?? 0).toFixed(1)}% selected</span>
      </div>
      {source ? (
        <div className="relative mx-auto w-full max-w-[900px]" style={{ aspectRatio: `${dimensions.width}/${dimensions.height}`, width: `min(100%, ${55 * dimensions.width / dimensions.height}vh)` }}>
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
              event.currentTarget.setPointerCapture(event.pointerId);
              drawing.current = true;
              last.current = null;
              paint(event);
            }}
            onPointerMove={paint}
            onPointerUp={() => { drawing.current = false; last.current = null; save(); }}
            onPointerCancel={() => { drawing.current = false; last.current = null; save(); }}
          />
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
