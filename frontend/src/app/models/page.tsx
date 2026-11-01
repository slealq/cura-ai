'use client';

import LibraryImage from '@/components/LibraryImage';

import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { billingApi, generationApi, jobsApi } from '@/lib/api';
import {
  Loader2,
  Box,
  X,
  Clock,
  CheckCircle,
  XCircle,
  Archive,
  Download,
  HardDrive,
  Copy,
  ExternalLink,
  Upload,
} from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import { cn, formatDate } from '@/lib/utils';
import Stage from '@/components/tools/Stage';
import SheetButton from '@/components/tools/SheetButton';
import Composer from '@/components/tools/Composer';
import type { LoraModel } from '@/types';
import { imagesApi } from '@/lib/api';
import TrainLoraModal from './components/TrainLoraModal';
import { useModelCatalog } from '@/hooks/useModelCatalog';

const statusConfig: Record<string, { icon: typeof Clock; color: string; label: string }> = {
  pending: { icon: Clock, color: 'text-warning bg-warning/10', label: 'Queued' },
  training: { icon: Loader2, color: 'text-selection bg-selection-soft', label: 'Running' },
  completed: { icon: CheckCircle, color: 'text-success bg-success/10', label: 'Ready' },
  failed: { icon: XCircle, color: 'text-danger bg-danger/10', label: 'Failed' },
  archived: { icon: Archive, color: 'text-muted-foreground bg-muted', label: 'Retired' },
  uploaded: { icon: Upload, color: 'text-success bg-success/10', label: 'Ready' },
};

function TrainingProgress({ model }: { model: LoraModel }) {
  const { data: job } = useQuery({
    queryKey: ['jobs', model.job_id],
    queryFn: () => jobsApi.get(model.job_id!),
    enabled: !!model.job_id && (model.status === 'training' || model.status === 'pending'),
    refetchInterval: 5000,
  });
  if (model.status !== 'training' && model.status !== 'pending') return null;
  const percent = job && job.total_items > 0 ? Math.min(100, job.progress / job.total_items * 100) : null;
  return (
    <div className="mt-3 space-y-1 text-xs text-muted-foreground" role="status">
      <span>{model.status === 'pending' ? 'Queued for training' : percent == null ? 'Training in progress' : `Training ${Math.round(percent)}%`}</span>
      {percent != null && <div className="h-1 rounded bg-muted"><div className="h-full rounded bg-selection" style={{ width: `${percent}%` }} /></div>}
      {model.job_id && <Link href="/jobs" className="block hover:underline">View training job #{model.job_id}</Link>}
    </div>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function isModelReady(model: LoraModel): boolean {
  return model.status === 'completed' || model.status === 'uploaded';
}

function UploadLoraModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', dismiss);
    return () => window.removeEventListener('keydown', dismiss);
  }, [open, onClose]);
  const queryClient = useQueryClient();
  const { data: catalog } = useModelCatalog();
  const BASE_MODELS = (catalog?.training_base_models ?? []).map(m => ({ value: m.key, label: m.label }));
  const [name, setName] = useState('');
  const [triggerWord, setTriggerWord] = useState('');
  const [baseModel, setBaseModel] = useState('flux-2');
  const [description, setDescription] = useState('');
  const [samplePromptsText, setSamplePromptsText] = useState('');
  const [file, setFile] = useState<File | null>(null);

  const uploadMutation = useMutation({
    mutationFn: generationApi.uploadLora,
    onSuccess: () => {
      toast.success('LoRA model uploaded successfully');
      queryClient.invalidateQueries({ queryKey: ['lora-models'] });
      onClose();
      setName('');
      setTriggerWord('');
      setBaseModel('flux-2');
      setDescription('');
      setSamplePromptsText('');
      setFile(null);
    },
    onError: (err: Error) => toast.error(err.message || 'Failed to upload LoRA'),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !name) return;
    const examplePrompts = samplePromptsText
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean);
    uploadMutation.mutate({
      name,
      trigger_word: triggerWord.trim() || undefined,
      base_model: baseModel,
      description: description || undefined,
      example_prompts: examplePrompts.length > 0 ? examplePrompts : undefined,
      file,
    });
  };

  if (!open) return null;

  return (
    <div className="contents">
      <div className="fixed inset-0 bg-black/50 z-50" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="mobile-modal bg-card rounded-xl shadow-xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Upload LoRA</h3>
            <button onClick={onClose} className="p-1 hover:bg-muted rounded-lg transition-colors">
              <X className="h-5 w-5" />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">.safetensors File</label>
              <input
                type="file"
                accept=".safetensors"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="w-full text-sm file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-primary file:text-primary-foreground hover:file:bg-primary/90 file:cursor-pointer"
              />
              {file && (
                <p className="text-xs text-muted-foreground mt-1">{(file.size / (1024 * 1024)).toFixed(1)} MB</p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My LoRA Model"
                className="w-full px-3 py-2 border border-border rounded-lg bg-background text-sm"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Trigger Word (optional)</label>
              <input
                type="text"
                value={triggerWord}
                onChange={(e) => setTriggerWord(e.target.value)}
                placeholder="e.g. TOK"
                className="w-full px-3 py-2 border border-border rounded-lg bg-background text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Base Model</label>
              <select
                value={baseModel}
                onChange={(e) => setBaseModel(e.target.value)}
                className="w-full px-3 py-2 border border-border rounded-lg bg-background text-sm"
              >
                {BASE_MODELS.map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Description (optional)</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                placeholder="Describe this LoRA model..."
                className="w-full px-3 py-2 border border-border rounded-lg bg-background text-sm resize-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Sample Prompts (optional)</label>
              <textarea
                value={samplePromptsText}
                onChange={(e) => setSamplePromptsText(e.target.value)}
                rows={3}
                placeholder="One prompt per line..."
                className="w-full px-3 py-2 border border-border rounded-lg bg-background text-sm resize-none"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Known prompts that work well with this model
              </p>
            </div>

            <button
              type="submit"
              disabled={!file || !name || uploadMutation.isPending}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors font-medium text-sm disabled:opacity-50"
            >
              {uploadMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Uploading...
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4" />
                  Upload LoRA
                </>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

function getSourceInfo(model: LoraModel): { label: string; href: string } | null {
  if (model.folder_id && model.folder_name) {
    return { label: `folder "${model.folder_name}"`, href: `/images/folder/${model.folder_id}` };
  }
  if (model.cluster_id && model.cluster_name) {
    return { label: `cluster "${model.cluster_name}"`, href: `/clusters/${model.cluster_id}` };
  }
  return null;
}

function TrainingPreview({ image }: { image: LoraModel['source_preview_images'][number] }) {
  const { data } = useQuery({
    queryKey: ['images', image.id],
    queryFn: () => imagesApi.get(image.id),
    enabled: !image.thumbnail_uri_small,
  });
  const thumbnail = image.thumbnail_uri_small || data?.thumbnail_uri_medium || data?.thumbnail_uri_small;
  const src = thumbnail
    ? imagesApi.getThumbnailUrl(thumbnail.split('/').pop()!)
    : data?.object_key ? imagesApi.getImageUrl(data.object_key.split('/').pop()!) : undefined;

  return (
    <Link href={`/images?image_id=${image.id}`} aria-label={`View training image ${image.id}`} className="h-[52px] w-[52px] shrink-0 overflow-hidden rounded bg-muted">
      {src && <LibraryImage src={src} alt="Training image" className="h-full w-full object-cover" />}
    </Link>
  );
}

function LoraModelCard({ model, selected, onClick, detailed }: {
  model: LoraModel;
  detailed?: boolean;
  selected: boolean;
  onClick: () => void;
}) {
  const { data, isError } = useQuery({
    queryKey: ['model-images', model.id],
    queryFn: () => generationApi.listImages({ lora_model_id: model.id, limit: 12 }),
    refetchInterval: 5000,
  });
  const config = statusConfig[model.status] || statusConfig.pending;
  const source = getSourceInfo(model);

  return (
    <section className={cn('border-b border-border pb-6 space-y-3', !detailed && 'model-list-row', selected && 'border-selection')}>
      <button onClick={onClick} aria-pressed={selected} className="flex w-full flex-wrap items-center gap-3 text-left">
        <h3 className="font-medium">{model.name}</h3>
        <span className={cn('rounded-full px-2 py-1 text-xs', config.color)}>{config.label}</span>
        <span className="text-xs text-muted-foreground">{model.base_model} · {model.training_images_count} training images{model.trigger_word ? ` · trigger ${model.trigger_word}` : ''}</span>
      </button>
      <TrainingProgress model={model} />
      {model.error_message && <p className="text-sm text-danger">{model.error_message}</p>}
      <h4 className="text-xs text-muted-foreground">Made with this model</h4>
      <div className="flex gap-2 overflow-x-auto">
        {data?.items.map(image => (
          <Link key={image.id} href={`/generate?lora=${model.id}&image=${image.id}`} className="relative h-[180px] w-[180px] shrink-0 overflow-hidden rounded-md bg-muted" aria-label={`Open image ${image.id} in Create`}>
            {image.status === 'completed' ? (
              <LibraryImage src={image.thumbnail_uri_medium ? generationApi.getThumbnailUrl(image.thumbnail_uri_medium.split('/').pop()!) : generationApi.getImageUrl(image.id)} alt={image.prompt} className="h-full w-full object-cover" />
            ) : (
              <span className="flex h-full items-center justify-center text-sm" role="status">{image.status === 'failed' ? 'Failed' : 'Generating…'}</span>
            )}
          </Link>
        ))}
        {!data?.items.length && <p className="py-8 text-sm text-muted-foreground">{isError ? 'Could not load images.' : data ? 'Try this model below to make its first image.' : 'Loading images…'}</p>}
      </div>
      <div className={detailed ? '' : 'hidden md:contents'}>
      <h4 className="text-xs text-muted-foreground">Trained on</h4>
      <div className="flex gap-2 overflow-x-auto">
        {model.source_preview_images?.map(image => (
          <TrainingPreview key={image.id} image={image} />
        ))}
        {!model.source_preview_images?.length && <p className="text-xs text-muted-foreground">{model.status === 'uploaded' ? 'External LoRA — training images not supplied.' : 'No training previews available.'}</p>}
        {source && <Link href={source.href} className="self-center text-xs underline">View {source.label}</Link>}
      </div>
      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground">Evaluation scores</summary>
        {model.latest_evaluation ? (
          <Link className="block py-2 underline" href={`/models/${model.id}/evaluations/${model.latest_evaluation.id}`}>
            {model.latest_evaluation.status}{model.latest_evaluation.overall_score != null ? ` · ${model.latest_evaluation.overall_score.toFixed(1)}/10` : ''} — View evaluation
          </Link>
        ) : <p className="py-2 text-muted-foreground">Not evaluated yet</p>}
        {isModelReady(model) && <Link className="underline" href={`/models/${model.id}/evaluate`}>Evaluate model</Link>}
      </details>
      </div>
      <button onClick={onClick} className="rounded-md border border-input px-3 py-1.5 text-xs">Try it & actions</button>
    </section>
  );
}

export default function ModelsPage() {
  const queryClient = useQueryClient();
  const [prompt, setPrompt] = useState('');
  const [mobileDetail, setMobileDetail] = useState(false);
  const [rename, setRename] = useState('');
  const [showTrainModal, setShowTrainModal] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const setSelectedModel = (model: LoraModel | null) => setSelectedModelId(model?.id ?? null);

  // Fetch LoRA models
  const { data: loraData, isLoading, isError: modelsError, refetch } = useQuery({
    queryKey: ['lora-models'],
    queryFn: () => generationApi.listLora(),
    refetchInterval: 5000,
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: generationApi.deleteLora,
    onSuccess: () => {
      toast.success('LoRA model deleted');
      queryClient.invalidateQueries({ queryKey: ['lora-models'] });
    },
    onError: () => toast.error('Failed to delete model'),
  });

  // Download weights mutations
  const downloadWeightsMutation = useMutation({
    mutationFn: generationApi.downloadLoraWeights,
    onSuccess: () => {
      toast.success('Weights download started');
      queryClient.invalidateQueries({ queryKey: ['lora-models'] });
    },
    onError: () => toast.error('Failed to start weights download'),
  });

  const downloadAllWeightsMutation = useMutation({
    mutationFn: generationApi.downloadAllLoraWeights,
    onSuccess: (data) => {
      toast.success(`Queued ${data.count} weight download(s)`);
      queryClient.invalidateQueries({ queryKey: ['lora-models'] });
    },
    onError: () => toast.error('Failed to start bulk weights download'),
  });

  const models = loraData?.items || [];
  const selectedModel = models.find((model) => model.id === selectedModelId) ?? models[0] ?? null;
  const activeId = selectedModel?.id;
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('mobile-model-title', { detail: mobileDetail ? selectedModel?.name ?? 'My models' : '' }));
    const back = () => setMobileDetail(false);
    window.addEventListener('mobile-model-back', back);
    return () => window.removeEventListener('mobile-model-back', back);
  }, [mobileDetail, selectedModel?.name]);
  const { data: estimate } = useQuery({
    queryKey: ['model-try-estimate', selectedModel?.base_model],
    queryFn: () => billingApi.estimateGenerationCost({ base_model: selectedModel!.base_model, with_lora: true }),
    enabled: !!selectedModel && isModelReady(selectedModel),
  });
  const tryMutation = useMutation({
    mutationFn: () => generationApi.generate({ prompt: prompt.trim(), base_model: selectedModel!.base_model, lora_model_id: selectedModel!.id, num_images: 1 }),
    onSuccess: () => {
      toast.success('Generation queued');
      queryClient.invalidateQueries({ queryKey: ['model-images'] });
      queryClient.invalidateQueries({ queryKey: ['generated-images'] });
    },
    onError: (error: Error) => toast.error(error.message || 'Could not generate'),
  });
  const updateMutation = useMutation({
    mutationFn: (values: { name?: string; retire?: boolean }) => generationApi.updateLora(activeId!, values),
    onSuccess: () => {
      toast.success('Model updated');
      setRename('');
      queryClient.invalidateQueries({ queryKey: ['lora-models'] });
    },
    onError: (error: Error) => toast.error(error.message || 'Could not update model'),
  });
  const recoverMutation = useMutation({
    mutationFn: generationApi.recoverLoraTraining,
    onSuccess: (result) => {
      if (result.status === 'failed') toast.error(result.error || 'Training failed');
      else toast.success(result.status === 'recovered' ? 'Training recovered' : 'Training status checked');
      queryClient.invalidateQueries({ queryKey: ['lora-models'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Could not recover training'),
  });
  const retryMutation = useMutation({
    mutationFn: generationApi.retryLoraTraining,
    onSuccess: () => {
      toast.success('Training retry started');
      queryClient.invalidateQueries({ queryKey: ['lora-models'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Could not retry training'),
  });
  const modelsWithoutWeights = models.filter((m) => isModelReady(m) && m.lora_url && !m.has_local_weights);

  return (
    <div className="-mx-5 -my-5 h-[calc(100%+40px)] min-h-0">
      <Stage
        canvas={
          <div className="space-y-6">
            {isLoading && <Loader2 className="h-6 w-6 animate-spin" />}
            {modelsError && (
              <div role="alert" className="text-sm text-danger">
                Could not load your models.
                <button onClick={() => refetch()} className="ml-2 underline">Retry</button>
              </div>
            )}
            {loraData && models.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Select images in the Library, then choose Train model to make your first model.
              </p>
            )}
            <div className="flex justify-between gap-2 md:hidden">
              {mobileDetail && <button className="min-h-10" onClick={() => setMobileDetail(false)}>All models</button>}
              <SheetButton title="Options" />
            </div>
            {models.map(model => (
              <div key={model.id} className={mobileDetail && activeId !== model.id ? 'hidden md:block' : ''}>
              <LoraModelCard
                key={model.id}
                model={model}
                detailed={mobileDetail && activeId === model.id}
                selected={activeId === model.id}
                onClick={() => {
                  setSelectedModel(model);
                  setRename('');
                  setMobileDetail(true);
                }}
              />
              </div>
            ))}
          </div>
        }
        composer={
          <Composer
            mobileHidden={!mobileDetail}
            value={prompt}
            onChange={setPrompt}
            onApply={() => tryMutation.mutate()}
            disabled={!selectedModel || !isModelReady(selectedModel) || !prompt.trim() || tryMutation.isPending}
            model={selectedModel?.name ?? 'Select a model'}
            count={1}
            cost={estimate?.estimated_sparks}
            placeholder="Try this model: describe an image"
            action="Try it"
            warning={selectedModel && !isModelReady(selectedModel)
              ? `Model ${statusConfig[selectedModel.status]?.label.toLowerCase() ?? selectedModel.status}`
              : undefined}
          />
        }
        settings={
          <>
            <h2 className="font-medium">My models</h2>
            <Link
              href="/images?tool=Train%20model"
              className="rounded-md bg-primary px-3 py-2 text-center text-primary-foreground"
            >
              Train from a library selection
            </Link>
            <button onClick={() => setShowUploadModal(true)} className="rounded-md border border-input px-3 py-2">Upload external LoRA</button>
            <button onClick={() => setShowTrainModal(true)} className="text-left text-xs underline">Train from a folder or cluster</button>
            <Link href="/settings" className="text-xs underline">Model settings</Link>
            {modelsWithoutWeights.length > 0 && (
              <button
                disabled={downloadAllWeightsMutation.isPending}
                onClick={() => downloadAllWeightsMutation.mutate()}
                className="text-left text-xs underline"
              >
                Download all weights ({modelsWithoutWeights.length})
              </button>
            )}
            {selectedModel && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">{selectedModel.name}</h3>
              </div>

              <p className={cn('rounded px-2 py-1', statusConfig[selectedModel.status]?.color)}>
                {statusConfig[selectedModel.status]?.label ?? selectedModel.status}
              </p>
              <form
                onSubmit={event => {
                  event.preventDefault();
                  if (rename.trim()) updateMutation.mutate({ name: rename.trim() });
                }}
                className="space-y-2"
              >
                <label htmlFor="model-name" className="block text-xs">Rename</label>
                <input
                  id="model-name"
                  value={rename}
                  onChange={event => setRename(event.target.value)}
                  placeholder={selectedModel.name}
                  maxLength={256}
                  className="w-full rounded-md border border-input bg-background px-2 py-2"
                />
                <button disabled={!rename.trim() || updateMutation.isPending} className="rounded-md border border-input px-3 py-1 disabled:opacity-50">Rename</button>
              </form>
              {isModelReady(selectedModel) && (
                <div className="flex flex-col items-start gap-2">
                  <Link href={`/generate?lora=${selectedModel.id}`} className="text-selection underline">
                    Open in Create
                  </Link>
                  <Link href={`/models/${selectedModel.id}/evaluate`} className="underline">
                    Evaluate model
                  </Link>
                  <button
                    disabled={updateMutation.isPending}
                    onClick={() => {
                      if (confirm(`Retire “${selectedModel.name}”? It will remain here with its images and weights, but cannot be used for new generations.`)) {
                        updateMutation.mutate({ retire: true });
                      }
                    }}
                    className="text-danger"
                  >
                    Retire
                  </button>
                </div>
              )}
              <TrainingProgress model={selectedModel} />
              <div className="space-y-3 text-sm">
                <div className="grid grid-cols-1 gap-3">
                  <div>
                    <span className="text-muted-foreground">Status</span>
                    <p className="font-medium">{selectedModel.status}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Trigger Word</span>
                    {selectedModel.trigger_word ? (
                      <p><code className="bg-muted px-1.5 py-0.5 rounded">{selectedModel.trigger_word}</code></p>
                    ) : (
                      <p className="text-muted-foreground italic text-xs">None</p>
                    )}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Base Model</span>
                    <p>{selectedModel.base_model}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Provider</span>
                    <p>{selectedModel.training_provider}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Training Images</span>
                    <p>{selectedModel.training_images_count}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Source</span>
                    {(() => {
                      const info = getSourceInfo(selectedModel);
                      return info ? (
                        <p>
                          <Link
                            href={info.href}
                            className="text-primary hover:underline"
                            onClick={() => setSelectedModel(null)}
                          >
                            {selectedModel.folder_name
                              ? `Folder: ${selectedModel.folder_name}`
                              : `Cluster: ${selectedModel.cluster_name}`}
                          </Link>
                        </p>
                      ) : (
                        <p>N/A</p>
                      );
                    })()}
                  </div>
                </div>

                {selectedModel.training_config && (
                  <div>
                    <span className="text-muted-foreground">Training Config</span>
                    <pre className="mt-1 whitespace-pre-wrap break-all text-xs">
                      {JSON.stringify(selectedModel.training_config, null, 2)}
                    </pre>
                  </div>
                )}

                {/* Weights storage status */}
                {(isModelReady(selectedModel) || selectedModel.status === 'archived') && (
                  <div>
                    <span className="text-muted-foreground">Weights Storage</span>
                    {selectedModel.has_local_weights ? (
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <div className="flex items-center gap-2">
                          <HardDrive className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                          <span className="text-sm text-emerald-700 dark:text-emerald-300">
                            Backed up{selectedModel.file_size ? ` (${formatFileSize(selectedModel.file_size)})` : ''}
                          </span>
                        </div>
                        <a
                          href={generationApi.getLoraWeightsUrl(selectedModel.id)}
                          download
                          className="flex items-center gap-1 px-2 py-1 text-xs bg-emerald-600 text-white rounded hover:bg-emerald-700 transition-colors"
                        >
                          <Download className="h-3 w-3" />
                          Download
                        </a>
                      </div>
                    ) : selectedModel.lora_url ? (
                      <div className="mt-1 flex items-center gap-2">
                        <span className="text-sm text-warning dark:text-amber-400">CDN only</span>
                        <button
                          onClick={() => downloadWeightsMutation.mutate(selectedModel.id)}
                          disabled={downloadWeightsMutation.isPending}
                          className="flex items-center gap-1 px-2 py-1 text-xs bg-primary text-primary-foreground rounded hover:bg-primary/90 transition-colors disabled:opacity-50"
                        >
                          {downloadWeightsMutation.isPending ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Download className="h-3 w-3" />
                          )}
                          Download Weights
                        </button>
                      </div>
                    ) : (
                      <p className="mt-1 text-sm text-muted-foreground">No weights available</p>
                    )}
                  </div>
                )}

                {/* Example Prompts */}
                {selectedModel.example_prompts && selectedModel.example_prompts.length > 0 && (
                  <div>
                    <span className="text-muted-foreground">Example Prompts</span>
                    <div className="mt-1.5 max-h-48 overflow-y-auto space-y-1.5">
                      {selectedModel.example_prompts.map((prompt, idx) => (
                        <div
                          key={idx}
                          className="flex items-start gap-2 p-2 bg-muted/50 rounded-lg group text-xs"
                        >
                          <p className="flex-1 line-clamp-2 text-foreground/80">{prompt}</p>
                          <div className="flex items-center gap-1 shrink-0">
                            <button
                              onClick={() => {
                                navigator.clipboard.writeText(prompt);
                                toast.success('Prompt copied');
                              }}
                              className="p-1 hover:bg-muted rounded transition-colors"
                              title="Copy prompt"
                            >
                              <Copy className="h-3 w-3" />
                            </button>
                            <Link
                              href={`/generate?lora=${selectedModel.id}&prompt=${encodeURIComponent(prompt)}`}
                              className="p-1 hover:bg-muted rounded transition-colors text-selection"
                              title="Try this prompt"
                              onClick={() => setSelectedModel(null)}
                            >
                              <ExternalLink className="h-3 w-3" />
                            </Link>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {selectedModel.error_message && (
                  <div className="p-3 bg-danger/10 rounded-lg">
                    <span className="text-danger font-medium">Error:</span>
                    <p className="text-danger mt-0.5">{selectedModel.error_message}</p>
                  </div>
                )}

                <div className="text-xs text-muted-foreground space-y-1">
                  <p>Created: {formatDate(selectedModel.created_at)}</p>
                  {selectedModel.training_started_at && (
                    <p>Training started: {formatDate(selectedModel.training_started_at)}</p>
                  )}
                  {selectedModel.training_completed_at && (
                    <p>Training completed: {formatDate(selectedModel.training_completed_at)}</p>
                  )}
                </div>
              </div>

              <div className="flex flex-wrap gap-2 border-t border-border pt-3 text-sm">
                {selectedModel.status === 'training' && <button disabled={recoverMutation.isPending} onClick={() => recoverMutation.mutate(selectedModel.id)} className="rounded-md border border-input px-3 py-2 disabled:opacity-50">Recover training</button>}
                {selectedModel.status === 'failed' && <button disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(selectedModel.id)} className="rounded-md border border-input px-3 py-2 disabled:opacity-50">Retry training</button>}
                <button onClick={() => { if (confirm(`Delete model “${selectedModel.name}”?`)) { deleteMutation.mutate(selectedModel.id); setSelectedModel(null); } }} className="rounded-md px-3 py-2 text-danger hover:bg-danger/10">Delete model</button>
              </div>
            </div>
            )}
          </>
        }
      />
      <TrainLoraModal open={showTrainModal} onClose={() => setShowTrainModal(false)} />
      <UploadLoraModal open={showUploadModal} onClose={() => setShowUploadModal(false)} />
    </div>
  );
}
