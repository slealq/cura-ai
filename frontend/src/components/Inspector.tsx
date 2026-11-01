'use client';

import ImageDeleteWarning from './ImageDeleteWarning';
import { clearDeleting, markDeleting } from '@/lib/deletingImages';

import { useMobileSheet } from '@/hooks/useMobileSheet';
import LibraryImage from '@/components/LibraryImage';

import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { Sparkles, X } from 'lucide-react';
import { toast } from 'sonner';
import {
  billingApi,
  clustersApi,
  foldersApi,
  generationApi,
  imagesApi,
  jobsApi,
  settingsApi,
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
  if (image.thumbnail_url) return image.thumbnail_url;
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
  clusterId,
  overview,
}: {
  clusterId?: number;
  overview?: React.ReactNode;
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
  const sheet = useMobileSheet(!!onDismiss, () => onDismiss?.());
  const [swipeY, setSwipeY] = useState(0);
  const router = useRouter();
  const client = useQueryClient();
  const { data: catalog } = useModelCatalog();
  const [model, setModel] = useState('');
  const [name, setName] = useState('');
  const [trigger, setTrigger] = useState('');
  const [folder, setFolder] = useState('');
  const { data: stats } = useQuery({ queryKey: ['pipeline-stats'], queryFn: imagesApi.getStats });
  const { data: folders } = useQuery({
    queryKey: ['folders', 'inspector'],
    queryFn: () => foldersApi.list({ limit: 200 }),
    enabled: tool === 'Add to folder',
  });
  const { data: visionCosts } = useQuery({
    queryKey: ['vision-costs', 'inspector'],
    queryFn: billingApi.getVisionCosts,
    enabled: tool === 'Describe',
  });
  const { data: providerConfig } = useQuery({
    queryKey: ['provider-config'],
    queryFn: settingsApi.getProviderConfig,
    enabled: tool === 'Describe',
  });
  const { data: trainingCosts } = useQuery({
    queryKey: ['training-costs'],
    queryFn: billingApi.getTrainingCosts,
    enabled: tool === 'Train model',
  });
  useEffect(() => {
    setName('');
    setTrigger('');
    setModel(catalog?.training_base_models[0]?.key ?? '');
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
  const models = (catalog?.training_base_models ?? []).map((m) => ({ id: m.key, label: m.label, provider: 'fal' }));
  const needsModel = tool === 'Train model';
  const invalid =
    (tool === 'Describe' && hasBatchRunning) ||
    (needsModel && !model) ||
    (tool === 'Train model' && (images.length < 5 || !name.trim())) ||
    (tool === 'Add to folder' && !folder && !name.trim()) ||
    (tool !== 'Recluster library' && !images.length);
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
        case 'Train model': {
          const trainingFolder = await foldersApi.create({ name: `${name.trim()} — training` });
          await foldersApi.addImages(trainingFolder.id, ids);
          await generationApi.trainLora({
            name: name.trim(),
            trigger_word: trigger.trim() || undefined,
            base_model: model,
            folder_id: trainingFolder.id,
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
          markDeleting(ids);
          await imagesApi.batchDelete(ids);
          break;
      }
      toast.success(
        ['Add to folder', 'Remove from folder'].includes(action) ? `${action} complete` : `${action} submitted`,
        {
          id: notice,
          action: {
            label: action === 'Train model' ? 'My models' : 'View Jobs',
            onClick: () => router.push(action === 'Train model' ? '/models' : '/jobs'),
          },
        }
      );
      await client.invalidateQueries();
    })().catch((error: Error) => {
      if (action === 'Delete') clearDeleting();
      toast.error(`${action} failed: ${error.message}`, { id: notice });
    });
  };
  const visionModel = providerConfig?.fal_vision_model || catalog?.defaults.vision_model;
  const languageCost = visionModel ? visionCosts?.costs.fal?.[visionModel] : undefined;
  const cost = tool === 'Train model' ? trainingCosts?.costs[model]
    : tool === 'Describe' && languageCost ? languageCost.total * images.length : undefined;
  return (
    <aside
      ref={sheet}
      role={onDismiss ? 'dialog' : undefined}
      aria-modal={onDismiss ? true : undefined}
      aria-label="Inspector"
      className="flex h-full min-h-[500px] w-full flex-col border-l border-border bg-background"
    >
      <header onTouchStart={e => setSwipeY(e.touches[0].clientY)} onTouchEnd={e => { if (e.changedTouches[0].clientY - swipeY > 80 && window.innerWidth < 768) onDismiss?.(); }} className="flex items-center justify-between border-b border-border p-4">
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
        {!tool && !images.length && overview}
        {!tool && !images.length && !overview && (
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
            {stats && stats.failed > 0 && (
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-danger">{stats.failed} failed</span>
                <button
                  onClick={() => {
                    const notice = toast.loading('Starting reprocess', {
                      action: { label: 'View Jobs', onClick: () => router.push('/jobs') },
                    });
                    void jobsApi.reprocessFailed().then(() => {
                      toast.success('Reprocessing failed images', { id: notice });
                      client.invalidateQueries({ queryKey: ['jobs'] });
                    }).catch(() => toast.error('Failed to start reprocess', { id: notice }));
                  }}
                  className="rounded-md px-2 py-1 font-medium text-muted-foreground hover:bg-accent"
                >
                  Reprocess failed
                </button>
              </div>
            )}
            <div className="grid grid-cols-2 gap-2">
              {(['Create', 'Edit', 'Ask Vision', 'Describe', 'Train model', 'Recluster library', 'Add to folder', ...(folderId ? ['Remove from folder'] : []), 'Delete'] as InspectorTool[]).map((t) => (
                <button
                  key={t}
                  onClick={() => onTool(t)}
                  disabled={!['Create', 'Recluster library', 'Edit', 'Ask Vision'].includes(t)}
                  className="rounded-lg border border-border p-3 text-left hover:bg-accent disabled:opacity-50"
                >
                  {t}
                  {!['Create', 'Edit', 'Ask Vision', 'Recluster library'].includes(t) && <span className="mt-1 block text-xs text-muted-foreground">Select images first</span>}
                </button>
              ))}
            </div>
          </>
        )}
        {!!images.length && (
          <div className="flex items-center gap-1">
            {images.slice(0, 6).map((image) => (
              <LibraryImage
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
                  'Create',
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
        {tool && !images.length && !['Create', 'Recluster library'].includes(tool) && (
          <p className="rounded-md border border-border bg-chrome p-3 text-muted-foreground">
            Select images in the grid to use this tool.
          </p>
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
        {['Add to folder', 'Remove from folder'].includes(tool || '') && (
          <p className="text-xs text-muted-foreground">
            This operation runs in the background of this tab. The current API does not create a trackable
            Job.
          </p>
        )}
        {tool === 'Delete' && <ImageDeleteWarning imageIds={images.map(image => image.id)} />}
        {tool === 'Delete' && (
          <p className="text-danger">
            Permanently delete {images.length} images from the library, folders and clusters? This cannot be
            undone.
          </p>
        )}
        {needsModel && (
          <label className="block space-y-2">
            <span>Model</span>
            <ModelPicker models={models} value={model} onChange={setModel} />
          </label>
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
                  Select at least 5 images. Your selection will be saved in “{name || 'Model name'} — training”
                  so you can revisit it or retry if training fails.
                </p>
              </>
            )}
          </>
        )}
        {!tool && clusterId && images.length > 0 && (
          <button className="w-full rounded-md border border-border p-2 text-left" onClick={() => {
            onClear();
            void Promise.all(images.map(image => clustersApi.excludeImage(clusterId, image.id)))
              .then(() => { toast.success('Images excluded from cluster'); return client.invalidateQueries(); })
              .catch((error: Error) => toast.error(error.message));
          }}>Exclude selected from cluster</button>
        )}

      </div>
      {tool && (
        <footer className="sticky bottom-0 space-y-3 border-t border-border bg-background p-4">
          {cost != null && (
            <p className="text-xs text-warning">
              ≈ {cost.toFixed(2)} sparks
              {tool === 'Describe' ? ' (typical image size)' : ''}
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
