'use client';

import { useQuery } from '@tanstack/react-query';
import { historyApi, imagesApi } from '@/lib/api';
import LibraryImage from './LibraryImage';
import type { Box } from './tools/BoxCanvas';
import { toast } from 'sonner';

export default function ImageHistoryPanel({ imageId, onOpen }: { imageId: number; onOpen: (id: number) => void }) {
  const { data, isError } = useQuery({ queryKey: ['image-history', imageId], queryFn: () => historyApi.get(imageId) });
  if (isError) return <p className="text-sm text-muted-foreground">History could not be loaded.</p>;
  if (!data) return null;
  const history = data.history;
  const open = (id: number) => onOpen(id);
  const usedToMake = <section className="space-y-3 text-sm"><h3 className="font-medium">Used to make</h3>
    {data.used_to_make.length ? <div className="flex flex-wrap gap-2">{data.used_to_make.map(result => <button key={result.id} className="max-w-24 text-left text-primary" onClick={() => open(result.id)} aria-label={result.filename || `Image ${result.id}`}>
      {result.thumbnail_uri && <LibraryImage className="h-20 w-24 rounded object-cover" src={imagesApi.getThumbnailUrl(result.thumbnail_uri)} alt="" />}
      <span className="block truncate text-xs">{result.filename || `Image ${result.id}`}</span>
    </button>)}</div> : <p className="text-muted-foreground">Not used to make any image yet.</p>}
  </section>;
  if (!history) return usedToMake;
  const maskIndex = history.inputs.findIndex(input => input.role === 'mask');
  const layout = (history.settings.bounding_boxes ?? []) as { label?: string; description: string; box?: Box; source_box?: Box; target_box?: Box }[];
  const contextBox = history.settings.context_window_box as Box | undefined;
  const base = history.inputs[0];
  const overlays = layout.flatMap(object => [
    ...(object.source_box ? [{ label: `${object.label} · source`, box: object.source_box }] : []),
    ...(object.target_box || object.box ? [{ label: `${object.label} · target`, box: (object.target_box || object.box)! }] : []),
  ]);
  if (contextBox && base?.width && base?.height) overlays.push({ label: 'Precision area', box: { x_min: contextBox.x_min / base.width, x_max: contextBox.x_max / base.width, y_min: contextBox.y_min / base.height, y_max: contextBox.y_max / base.height } });
  const settings = { ...history.settings, Seed: history.seed ?? 'Not saved', Cost: history.charged_cost == null ? 'Not saved' : `${Math.round(history.charged_cost * 100000) / 100} sparks` };
  return <section className="space-y-5 text-sm" aria-label="How it was made">
    <div><h3 className="font-semibold">How it was made</h3><p className="text-xs text-muted-foreground">{history.job_type === 'edit' ? 'Edit' : 'Create'} · {new Date(history.date).toLocaleString()}</p></div>
    {history.partial && <p className="rounded bg-muted px-2 py-1 text-xs">Partial history</p>}
    {!!overlays.length && base?.copy_key && (
      <section className="space-y-2" aria-label="Saved boxes">
        <h4 className="text-xs font-medium text-muted-foreground">Saved boxes</h4>
        <div className="relative max-w-md overflow-hidden rounded">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={historyApi.inputUrl(imageId, 0)} alt="Original base with saved boxes" className="block w-full" />
          {overlays.map(({ label, box }, index) => (
            <div key={index} className="absolute border-2 border-primary bg-primary/10" style={{ left: `${box.x_min * 100}%`, top: `${box.y_min * 100}%`, width: `${(box.x_max - box.x_min) * 100}%`, height: `${(box.y_max - box.y_min) * 100}%` }}>
              <span className="bg-background/90 px-1 text-xs">{label}</span>
            </div>
          ))}
        </div>
        {layout.map((object, index) => <p key={index} className="text-xs">&lt;{object.label}&gt;: {object.description}</p>)}
      </section>
    )}
    {maskIndex >= 0 && history.inputs[0]?.copy_key && history.inputs[maskIndex].copy_key && (
      <section className="space-y-2" aria-label="Painted area over base">
        <h4 className="text-xs font-medium text-muted-foreground">Painted area over base</h4>
        <div className="relative isolate max-w-md overflow-hidden rounded bg-black">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={historyApi.inputUrl(imageId, 0)} alt="Original base" className="block w-full" />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={historyApi.inputUrl(imageId, maskIndex)} alt="White highlights the painted area" className="absolute inset-0 h-full w-full opacity-60 mix-blend-screen" />
        </div>
        <p className="text-xs text-muted-foreground">The highlighted area was selected for editing.</p>
      </section>
    )}
    {!!history.inputs.length && <div className="space-y-2 border-t border-border pt-4"><h4 className="text-xs font-medium text-muted-foreground">Inputs</h4>
      <div className="flex flex-wrap gap-2">{history.inputs.map((input, index) => {
        const content = <><span className="block text-xs">{input.label}{input.role === 'reference' ? ' · composition reference' : ''}</span>{input.copy_key ?
          // eslint-disable-next-line @next/next/no-img-element
          <img className={`h-20 w-24 rounded object-cover ${input.image_id ? '' : 'grayscale opacity-50'}`} src={historyApi.inputUrl(imageId, index)} alt={input.filename} /> : <span className="block h-20 w-24 rounded bg-muted p-2 text-xs">No copy was saved</span>}
          <span className="block max-w-24 truncate text-xs" title={input.filename}>{input.filename}</span></>;
        return input.image_id ? <button key={index} aria-label={`Open ${input.label}`} onClick={() => open(input.image_id!)}>{content}</button> : <div key={index}>{content}</div>;
      })}</div>
      {history.inputs.map((input, index) => !input.image_id && <p key={index} className="text-xs text-muted-foreground">{input.label}: {input.copy_key ? (input.role === 'mask' ? 'saved paint mask (white means edit).' : input.uploaded ? 'uploaded input. This is a low-resolution copy.' : 'the original image was deleted. This is a low-resolution copy.') : 'the original image is unavailable. No copy was saved.'}</p>)}
    </div>}
    <div className="space-y-2 border-t border-border pt-4"><h4 className="text-xs font-medium text-muted-foreground">Prompt</h4><p className="whitespace-pre-wrap border-l-2 border-border pl-3">{history.prompt}</p>
      <button className="text-primary underline" onClick={() => void navigator.clipboard.writeText(history.prompt).then(() => toast.success('Prompt copied')).catch(() => toast.error('Could not copy prompt'))}>Copy prompt</button>
      {history.negative_prompt && <><h4 className="text-xs text-muted-foreground">Negative prompt</h4><p className="whitespace-pre-wrap">{history.negative_prompt}</p></>}
    </div>
    <div className="space-y-2 border-t border-border pt-4"><h4 className="text-xs font-medium text-muted-foreground">Model</h4><p>{history.model.name} {!history.model.offered && <span className="rounded bg-muted px-2 py-1 text-xs">No longer offered</span>}</p><p className="text-xs text-muted-foreground">{history.provider}</p></div>
    {!!history.loras.length && <div className="space-y-2 border-t border-border pt-4"><h4 className="text-xs font-medium text-muted-foreground">LoRA</h4>{history.loras.map((lora, index) => <div key={index}><p>{lora.name} {lora.deleted && <span className="rounded bg-muted px-2 py-1 text-xs">Deleted</span>}</p><p className="text-xs text-muted-foreground">Strength: {lora.strength} · Base model: {lora.base_model || 'Not saved'} · Trigger word: {lora.trigger_word || 'None'}</p></div>)}</div>}
    <div className="space-y-2 border-t border-border pt-4"><h4 className="text-xs font-medium text-muted-foreground">Settings</h4><dl className="grid grid-cols-2 gap-2">{Object.entries(settings).map(([key, value]) => <div className="contents" key={key}><dt className="break-words text-muted-foreground">{key.replaceAll('_', ' ')}</dt><dd className="break-words text-right">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl></div>
    {!!data.used_to_make.length && <div className="border-t border-border pt-4">{usedToMake}</div>}
  </section>;
}
