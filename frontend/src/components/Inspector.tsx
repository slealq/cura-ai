'use client';

import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { Sparkles, X } from 'lucide-react';
import { toast } from 'sonner';
import {
  billingApi,
  clustersApi,
  editApi,
  foldersApi,
  generationApi,
  imagesApi,
  jobsApi,
  settingsApi,
  visionApi,
} from '@/lib/api';
import { useModelCatalog } from '@/hooks/useModelCatalog';
import type { Image } from '@/types';
import ModelPicker from './ModelPicker';

export type InspectorTool =
  | 'Describe'
  | 'Recluster library'
  | 'Edit'
  | 'Ask Vision'
  | 'Train model'
  | 'Add to folder'
  | 'Remove from folder'
  | 'Delete'
  | 'Create';
export const thumbnail = (image: Image) => {
  const uri = image.thumbnail_uri_small || image.thumbnail_uri_medium;
  return uri ? imagesApi.getThumbnailUrl(uri.split('/').pop()!) : imagesApi.getImageUrl(image.object_key);
};
const field = 'w-full rounded-md border border-input bg-background px-3 py-2 text-sm';

export default function Inspector({
  title,
  total,
  images,
  tool,
  onTool,
  onClear,
  folderId,
  hasBatchRunning,
  onDispatched,
  onDismiss,
}: {
  title: string;
  total: number;
  images: Image[];
  tool: InspectorTool | null;
  onTool: (tool: InspectorTool | null) => void;
  onClear: () => void;
  folderId?: number;
  hasBatchRunning: boolean;
  onDispatched: () => void;
  onDismiss?: () => void;
}) {
  const router = useRouter();
  const client = useQueryClient();
  const { data: catalog } = useModelCatalog();
  const [prompt, setPrompt] = useState('');
  const [model, setModel] = useState('');
  const [name, setName] = useState('');
  const [trigger, setTrigger] = useState('');
  const [count, setCount] = useState(1);
  const [folder, setFolder] = useState('');
  const [lora, setLora] = useState('');
  const { data: stats } = useQuery({ queryKey: ['pipeline-stats'], queryFn: imagesApi.getStats });
  const { data: folders } = useQuery({
    queryKey: ['folders', 'inspector'],
    queryFn: () => foldersApi.list({ limit: 200 }),
    enabled: tool === 'Add to folder',
  });
  const { data: loras } = useQuery({
    queryKey: ['lora-models', 'inspector'],
    queryFn: () => generationApi.listLora({ status: 'completed,uploaded', limit: 200 }),
    enabled: tool === 'Create',
  });
  const { data: generationCost } = useQuery({
    queryKey: ['inspector-estimate', model, lora],
    queryFn: () => billingApi.estimateGenerationCost({ base_model: model, with_lora: !!lora }),
    enabled: tool === 'Create' && !!model,
  });
  const { data: visionCosts } = useQuery({
    queryKey: ['vision-costs', 'inspector'],
    queryFn: billingApi.getVisionCosts,
    enabled: tool === 'Describe' || tool === 'Ask Vision',
  });
  const { data: providerConfig } = useQuery({
    queryKey: ['provider-config'],
    queryFn: settingsApi.getProviderConfig,
    enabled: tool === 'Describe',
  });
  const { data: generationCosts } = useQuery({
    queryKey: ['generation-costs'],
    queryFn: billingApi.getGenerationCosts,
    enabled: tool === 'Create',
  });
  const { data: editCosts } = useQuery({
    queryKey: ['edit-costs'],
    queryFn: billingApi.getEditCosts,
    enabled: tool === 'Edit',
  });
  const { data: trainingCosts } = useQuery({
    queryKey: ['training-costs'],
    queryFn: billingApi.getTrainingCosts,
    enabled: tool === 'Train model',
  });
  useEffect(() => {
    setPrompt('');
    setName('');
    setTrigger('');
    setCount(1);
    setLora('');
    setModel(
      tool === 'Create'
        ? (catalog?.defaults.generation_model ?? '')
        : tool === 'Edit'
          ? (catalog?.defaults.edit_model ?? '')
          : tool === 'Train model'
            ? (catalog?.training_base_models[0]?.key ?? '')
            : (catalog?.defaults.vision_model ?? '')
    );
  }, [tool, catalog]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && tool) {
        e.stopImmediatePropagation();
        onTool(null);
      }
    };
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  }, [tool, onTool]);
  const imageModels = tool === 'Edit' ? catalog?.edit : catalog?.generation;
  const chosen = imageModels?.find((m) => m.key === model);
  const maxSources = chosen?.max_source_images || 1;
  const models =
    tool === 'Train model'
      ? (catalog?.training_base_models ?? []).map((m) => ({ id: m.key, label: m.label, provider: 'fal' }))
      : tool === 'Ask Vision'
        ? (catalog?.language ?? []).map((m) => ({
            id: m.id,
            label: m.label,
            provider: m.vendor,
            cost: visionCosts?.costs.fal?.[m.id]?.describe,
          }))
        : (imageModels ?? []).map((m) => ({
            id: m.key,
            label: m.label,
            provider: m.vendor,
            cost: tool === 'Edit' ? editCosts?.costs[m.key] : generationCosts?.costs[m.key]?.without_lora,
          }));
  const needsModel = ['Create', 'Edit', 'Ask Vision', 'Train model'].includes(tool || '');
  const invalid =
    (tool === 'Describe' && hasBatchRunning) ||
    (needsModel && !model) ||
    (['Create', 'Edit', 'Ask Vision'].includes(tool || '') && !prompt.trim()) ||
    (tool === 'Edit' && images.length > maxSources) ||
    (tool === 'Ask Vision' && images.length > 10) ||
    (tool === 'Train model' && (images.length < 10 || !name.trim())) ||
    (tool === 'Add to folder' && !folder && !name.trim()) ||
    (tool !== 'Create' && tool !== 'Recluster library' && !images.length);
  const dispatch = () => {
    if (!tool || invalid) return;
    const action = tool;
    const ids = images.map((i) => i.id);
    onTool(null);
    onClear();
    onDispatched();
    const notice = toast.loading(`${action} started`, {
      action: { label: 'View Jobs', onClick: () => router.push('/jobs') },
    });
    void (async () => {
      switch (action) {
        case 'Describe':
          await jobsApi.reprocessSelected(ids);
          break;
        case 'Recluster library':
          await clustersApi.recluster();
          break;
        case 'Edit':
          await editApi.edit({ prompt, edit_model: model, source_image_ids: ids, num_images: 1 });
          break;
        case 'Create':
          await generationApi.generate({
            prompt,
            base_model: model,
            num_images: count,
            ...(lora ? { lora_model_id: Number(lora) } : {}),
          });
          break;
        case 'Ask Vision':
          for (let n = 0; n < ids.length; n++) {
            await visionApi.analyze({
              source_image_id: ids[n],
              provider: 'fal',
              model,
              mode: 'custom',
              custom_prompt: prompt,
            });
            toast.loading(`Analyzed ${n + 1}/${ids.length}`, { id: notice });
          }
          break;
        case 'Train model': {
          const trainingFolder = await foldersApi.create({ name: `${name.trim()} — training` });
          await foldersApi.addImages(trainingFolder.id, ids);
          await generationApi.trainLora({
            name: name.trim(),
            trigger_word: trigger.trim() || undefined,
            base_model: model,
            folder_id: trainingFolder.id,
            steps: model === 'qwen-image-2512' ? 2000 : 1000,
            use_captions: true,
            caption_include_tags: true,
            caption_include_description: true,
          });
          break;
        }
        case 'Add to folder': {
          const id = name.trim() ? (await foldersApi.create({ name: name.trim() })).id : Number(folder);
          await foldersApi.addImages(id, ids);
          break;
        }
        case 'Remove from folder':
          await foldersApi.removeImages(folderId!, ids);
          break;
        case 'Delete':
          await imagesApi.batchDelete(ids);
          break;
      }
      toast.success(
        action === 'Ask Vision'
          ? 'Analysis ready in Vision'
          : ['Add to folder', 'Remove from folder', 'Delete'].includes(action)
            ? `${action} complete`
            : `${action} submitted`,
        {
          id: notice,
          action: {
            label: action === 'Ask Vision' ? 'View results' : 'View Jobs',
            onClick: () => router.push(action === 'Ask Vision' ? '/vision' : '/jobs'),
          },
        }
      );
      await client.invalidateQueries();
    })().catch((error: Error) => toast.error(`${action} failed: ${error.message}`, { id: notice }));
  };
  const visionModel =
    tool === 'Describe' ? providerConfig?.fal_vision_model || catalog?.defaults.vision_model : model;
  const languageCost = visionModel ? visionCosts?.costs.fal?.[visionModel] : undefined;
  const cost =
    tool === 'Create'
      ? generationCost?.estimated_sparks != null
        ? generationCost.estimated_sparks * count
        : undefined
      : tool === 'Edit'
        ? editCosts?.costs[model]
        : tool === 'Train model'
          ? trainingCosts?.costs[model]
          : tool === 'Describe' && languageCost
            ? languageCost.total * images.length
            : tool === 'Ask Vision' && languageCost
              ? languageCost.describe * images.length
              : undefined;
  return (
    <aside
      aria-label="Inspector"
      className="flex h-full min-h-[500px] w-full flex-col border-l border-border bg-background"
    >
      <header className="flex items-center justify-between border-b border-border p-4">
        <h2 className="flex items-center gap-2 font-medium">
          <Sparkles className="h-4 w-4" />
          {tool || (images.length ? `${images.length} selected` : title)}
        </h2>
        <button
          aria-label={tool ? 'Close tool' : 'Clear selection'}
          onClick={() => (tool ? onTool(null) : onClear())}
          className="rounded p-1 hover:bg-accent"
        >
          {tool ? <X className="h-4 w-4" /> : images.length ? 'Clear' : null}
        </button>
        {onDismiss && (
          <button aria-label="Close inspector" onClick={onDismiss} className="rounded p-1 hover:bg-accent">
            <X className="h-4 w-4" />
          </button>
        )}
      </header>
      <div className="flex-1 space-y-5 overflow-y-auto p-4 text-sm">
        {!tool && !images.length && (
          <>
            <p className="text-muted-foreground">{total} images in this view</p>
            <h3 className="font-medium">Library health</h3>
            {stats &&
              [
                ['Described', stats.described + stats.embedded + stats.clustered],
                ['Clustered', stats.clustered],
              ].map(([label, value]) => (
                <div key={label}>
                  <div className="mb-2 flex justify-between text-xs">
                    <span>{label}</span>
                    <span>
                      {value} / {stats.total_images}
                    </span>
                  </div>
                  <div className="h-1 rounded bg-muted">
                    <div
                      className="h-1 rounded bg-selection"
                      style={{ width: `${(Number(value) / Math.max(stats.total_images, 1)) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            <p className="text-xs text-muted-foreground">Health covers the whole library.</p>
            <div className="grid grid-cols-2 gap-2">
              {(['Create', 'Recluster library'] as InspectorTool[]).map((t) => (
                <button
                  key={t}
                  onClick={() => onTool(t)}
                  className="rounded-lg border border-border p-3 hover:bg-accent"
                >
                  {t}
                </button>
              ))}
            </div>
          </>
        )}
        {!!images.length && (
          <div className="flex items-center gap-1">
            {images.slice(0, 6).map((image) => (
              <img
                key={image.id}
                src={thumbnail(image)}
                alt="Selected image"
                className="h-10 w-10 rounded object-cover"
              />
            ))}
            {images.length > 6 && <span className="text-xs">+{images.length - 6}</span>}
          </div>
        )}
        {!tool && !!images.length && (
          <>
            <div className="grid grid-cols-2 gap-2">
              {(
                [
                  'Describe',
                  'Recluster library',
                  'Edit',
                  'Ask Vision',
                  'Train model',
                  'Add to folder',
                  ...(folderId ? ['Remove from folder'] : []),
                ] as InspectorTool[]
              ).map((t) => (
                <button
                  key={t}
                  onClick={() => onTool(t)}
                  className="rounded-lg border border-border p-3 text-left hover:bg-accent"
                >
                  {t}
                </button>
              ))}
            </div>
            <div className="space-y-2 text-xs text-muted-foreground">
              <p>{images.filter((i) => !i.metadata?.description_long).length} not described</p>
              <p>{images.filter((i) => i.status === 'failed').length} failed</p>
              <p>
                {images.filter((i) => ['generated', 'edited'].includes(i.source)).length} generated or edited
              </p>
            </div>
            <button onClick={() => onTool('Delete')} className="text-danger">
              Delete selected images…
            </button>
          </>
        )}
        {tool === 'Describe' && (
          <p>
            {hasBatchRunning
              ? 'A describe batch is already running. Wait for it to finish.'
              : 'Tag, describe and embed the selected images using your configured defaults.'}
          </p>
        )}
        {tool === 'Recluster library' && (
          <p>This reclusters the whole library, including images outside this selection.</p>
        )}
        {['Add to folder', 'Remove from folder', 'Delete'].includes(tool || '') && (
          <p className="text-xs text-muted-foreground">
            This operation runs in the background of this tab. The current API does not create a trackable
            Job.
          </p>
        )}
        {tool === 'Delete' && (
          <p className="text-danger">
            Permanently delete {images.length} images from the library, folders and clusters? This cannot be
            undone.
          </p>
        )}
        {needsModel && (
          <>
            <label className="block space-y-2">
              <span>Model</span>
              <ModelPicker
                models={models}
                value={model}
                onChange={(id) => {
                  setModel(id);
                  setCount(1);
                  setLora('');
                }}
              />
            </label>
            {['Create', 'Edit', 'Ask Vision'].includes(tool || '') && (
              <label className="block space-y-2">
                <span>{tool === 'Ask Vision' ? 'Question' : 'Prompt'}</span>
                <textarea
                  className={`${field} min-h-32`}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                />
              </label>
            )}
          </>
        )}
        {tool === 'Edit' && (
          <p className="text-xs text-muted-foreground">
            Selected images are combined as sources for one edit. This model accepts up to {maxSources} source
            images; {images.length} selected.
          </p>
        )}
        {tool === 'Ask Vision' && (
          <p className="text-xs text-muted-foreground">
            Single-image analysis runs sequentially, up to 10 selected images. This API does not create Jobs;
            progress appears in a toast and results in Vision.
          </p>
        )}
        {tool === 'Create' && (
          <>
            <label className="block space-y-2">
              <span>Images</span>
              <input
                type="number"
                min={1}
                max={chosen?.max_num_images || 1}
                value={count}
                onChange={(e) =>
                  setCount(Math.max(1, Math.min(chosen?.max_num_images || 1, Number(e.target.value) || 1)))
                }
                className={field}
              />
            </label>
            {chosen?.supports_lora && (
              <label className="block space-y-2">
                <span>LoRA (optional)</span>
                <select className={field} value={lora} onChange={(e) => setLora(e.target.value)}>
                  <option value="">None</option>
                  {loras?.items
                    .filter((l) => l.base_model === model)
                    .map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name}
                      </option>
                    ))}
                </select>
              </label>
            )}
          </>
        )}
        {(tool === 'Train model' || tool === 'Add to folder') && (
          <>
            {tool === 'Add to folder' && (
              <label className="block space-y-2">
                <span>Existing folder</span>
                <select
                  className={field}
                  value={folder}
                  onChange={(e) => {
                    setFolder(e.target.value);
                    setName('');
                  }}
                >
                  <option value="">Choose folder</option>
                  {folders?.items.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="block space-y-2">
              <span>{tool === 'Train model' ? 'Model name' : 'Or create a new folder'}</span>
              <input className={field} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            {tool === 'Train model' && (
              <>
                <label className="block space-y-2">
                  <span>Trigger word (optional)</span>
                  <input className={field} value={trigger} onChange={(e) => setTrigger(e.target.value)} />
                </label>
                <p className="text-xs text-muted-foreground">
                  Requires at least 10 images. A folder named “{name || 'Model name'} — training” will be
                  created from this selection because training accepts folders, not image IDs. The folder
                  remains available if training fails.
                </p>
              </>
            )}
          </>
        )}
      </div>
      {tool && (
        <footer className="sticky bottom-0 space-y-3 border-t border-border bg-background p-4">
          {cost != null && (
            <p className="text-xs text-warning">
              ≈ {cost.toFixed(2)} sparks
              {tool === 'Ask Vision' || tool === 'Describe' ? ' (typical image size)' : ''}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button
              onClick={() => onTool(null)}
              className="rounded-md border border-border px-3 py-2 text-sm"
            >
              Cancel
            </button>
            <button
              disabled={!!invalid}
              onClick={dispatch}
              className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-40"
            >
              {tool}
            </button>
          </div>
        </footer>
      )}
    </aside>
  );
}
