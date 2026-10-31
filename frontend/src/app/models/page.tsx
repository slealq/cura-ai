'use client';

import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { generationApi, jobsApi } from '@/lib/api';
import {
  Loader2,
  Plus,
  Box,
  Trash2,
  X,
  Sparkles,
  Clock,
  CheckCircle,
  XCircle,
  Archive,
  FlaskConical,
  Download,
  HardDrive,
  Copy,
  ExternalLink,
  Upload,
} from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import { cn, formatDate } from '@/lib/utils';
import type { LoraModel } from '@/types';
import { imagesApi } from '@/lib/api';
import TrainLoraModal from './components/TrainLoraModal';
import { useModelCatalog } from '@/hooks/useModelCatalog';

const statusConfig: Record<string, { icon: typeof Clock; color: string; label: string }> = {
  pending: { icon: Clock, color: 'text-warning bg-warning/10', label: 'Needs attention' },
  training: { icon: Loader2, color: 'text-selection bg-selection-soft', label: 'Running' },
  completed: { icon: CheckCircle, color: 'text-success bg-success/10', label: 'Ready' },
  failed: { icon: XCircle, color: 'text-danger bg-danger/10', label: 'Failed' },
  archived: { icon: Archive, color: 'text-muted-foreground bg-muted', label: 'Archived' },
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
        <div className="bg-card rounded-xl shadow-xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()}>
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

function LoraModelCard({
  model,
  onDelete,
  onClick,
  selected,
}: {
  selected: boolean;
  model: LoraModel;
  onDelete: () => void;
  onClick: () => void;
}) {
  const { data: catalog } = useModelCatalog();
  const config = statusConfig[model.status] || statusConfig.pending;
  const StatusIcon = config.icon;
  const sourceInfo = getSourceInfo(model);
  const previews = model.source_preview_images?.filter((p) => p.thumbnail_uri_small) || [];

  return (
    <div
      className={cn('bg-background border rounded-lg overflow-hidden hover:border-selection/50 transition-colors cursor-pointer', selected ? 'border-selection ring-1 ring-selection' : 'border-border')}
      onClick={onClick}
      onKeyDown={(event) => { if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onClick(); } }}
      tabIndex={0}
      role="button"
      aria-label={`Inspect ${model.name}`}
      aria-pressed={selected}
    >
      {/* Preview images strip */}
      {previews.length > 0 ? (
        <div className="flex h-24 bg-muted/30">
          {previews.map((img) => (
            <div key={img.id} className="flex-1 min-w-0 relative">
              <img
                src={imagesApi.getThumbnailUrl(img.thumbnail_uri_small!.split('/').pop()!)}
                alt=""
                className="absolute inset-0 w-full h-full object-cover"
              />
            </div>
          ))}
        </div>
      ) : (
        <div className="flex h-24 bg-muted/30 items-center justify-center">
          <Box className="h-8 w-8 text-muted-foreground/30" />
        </div>
      )}

      <div className="p-5">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="font-semibold text-sm">{model.name}</h3>
            {model.trigger_word && (
              <p className="text-xs text-muted-foreground mt-0.5">
                Trigger: <code className="bg-muted px-1 py-0.5 rounded">{model.trigger_word}</code>
              </p>
            )}
          </div>

          <span className={cn('flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium', config.color)}>
            <StatusIcon className={cn('h-3 w-3', model.status === 'training' && 'animate-spin')} />
            {config.label}
          </span>
        </div>

        <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground items-center">
          <span>{model.training_images_count} images</span>
          <span className={cn('px-1.5 py-0.5 rounded-full text-[10px] font-semibold', 'bg-muted text-muted-foreground')}>
            {catalog?.training_base_models.find((m) => m.key === model.base_model)?.label || model.base_model}
          </span>
          {model.has_local_weights && model.file_size && (
            <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
              <HardDrive className="h-3 w-3" />
              {formatFileSize(model.file_size)}
            </span>
          )}
          {sourceInfo && (
            <Link
              href={sourceInfo.href}
              onClick={(e) => e.stopPropagation()}
              className="text-primary hover:underline"
            >
              from {sourceInfo.label}
            </Link>
          )}
        </div>

        <TrainingProgress model={model} />

        {/* Evaluation info */}
        {isModelReady(model) && (
          <div className="mt-3">
            {model.latest_evaluation ? (
              <Link
                href={`/models/${model.id}/evaluations/${model.latest_evaluation.id}`}
                onClick={(e) => e.stopPropagation()}
                className="flex items-center gap-2 text-xs px-2.5 py-1.5 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
              >
                <FlaskConical className="h-3 w-3 text-warning flex-shrink-0" />
                {model.latest_evaluation.status === 'completed' && model.latest_evaluation.overall_score != null ? (
                  <span>
                    Score: <span className="font-semibold text-foreground">{model.latest_evaluation.overall_score.toFixed(1)}</span>
                    <span className="text-muted-foreground">/10</span>
                  </span>
                ) : model.latest_evaluation.status === 'running' ? (
                  <span className="flex items-center gap-1 text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Evaluating...
                  </span>
                ) : model.latest_evaluation.status === 'failed' ? (
                  <span className="text-danger">Evaluation failed</span>
                ) : (
                  <span className="text-muted-foreground">Evaluation pending</span>
                )}
              </Link>
            ) : (
              <span className="text-[10px] text-muted-foreground/60 italic">Not evaluated yet</span>
            )}
          </div>
        )}

        {model.error_message && (
          <p className="mt-2 text-xs text-danger line-clamp-1">{model.error_message}</p>
        )}

        <div className="mt-3 flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground">
            {formatDate(model.created_at)}
          </span>
          <div className="flex items-center gap-1">
            {isModelReady(model) && (
              <>
                {model.has_local_weights && (
                  <a
                    href={generationApi.getLoraWeightsUrl(model.id)}
                    download
                    onClick={(e) => e.stopPropagation()}
                    className="p-1.5 hover:bg-muted rounded-lg transition-colors text-emerald-600"
                    title="Download .safetensors"
                  >
                    <Download className="h-4 w-4" />
                  </a>
                )}
                <Link
                  href={`/models/${model.id}/evaluate`}
                  onClick={(e) => e.stopPropagation()}
                  className="p-1.5 hover:bg-muted rounded-lg transition-colors text-warning"
                  title="Evaluate model quality"
                >
                  <FlaskConical className="h-4 w-4" />
                </Link>
                <Link
                  href={`/generate?lora=${model.id}`}
                  onClick={(e) => e.stopPropagation()}
                  className="p-1.5 hover:bg-muted rounded-lg transition-colors text-selection"
                  title="Generate with this LoRA"
                >
                  <Sparkles className="h-4 w-4" />
                </Link>
              </>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="p-1.5 hover:bg-danger/10 rounded-lg transition-colors text-muted-foreground hover:text-danger"
              title="Delete"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ModelsPage() {
  const queryClient = useQueryClient();
  const [showTrainModal, setShowTrainModal] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const setSelectedModel = (model: LoraModel | null) => setSelectedModelId(model?.id ?? null);

  // Fetch LoRA models
  const { data: loraData, isLoading } = useQuery({
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
  const selectedModel = models.find((model) => model.id === selectedModelId) ?? null;
  const { data: usage, isError: usageError } = useQuery({
    queryKey: ['model-usage', selectedModelId],
    queryFn: () => generationApi.listImages({ lora_model_id: selectedModelId!, limit: 1 }),
    enabled: selectedModelId != null,
    refetchInterval: 10000,
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
    <div className="flex items-start gap-5">
      <div className="min-w-0 flex-1 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Models</h1>
          <p className="text-muted-foreground mt-1">
            Train and manage LoRA adapters for image generation
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {modelsWithoutWeights.length > 0 && (
            <button
              onClick={() => downloadAllWeightsMutation.mutate()}
              disabled={downloadAllWeightsMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 border border-border text-foreground rounded-lg hover:bg-muted transition-colors font-medium text-sm disabled:opacity-50"
            >
              {downloadAllWeightsMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              Download All Weights ({modelsWithoutWeights.length})
            </button>
          )}
          <button
            onClick={() => setShowUploadModal(true)}
            className="flex items-center gap-2 px-4 py-2 border border-border text-foreground rounded-lg hover:bg-muted transition-colors font-medium text-sm"
          >
            <Upload className="h-4 w-4" />
            Upload LoRA
          </button>
          <button
            onClick={() => setShowTrainModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors font-medium text-sm"
          >
            <Plus className="h-4 w-4" />
            Train New LoRA
          </button>
        </div>
      </div>

      {/* Models Grid */}
      {isLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : models.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <Box className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>No LoRA models yet</p>
          <p className="text-sm mt-1">Train your first model from a folder or cluster of images</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4">
          {models.map((model) => (
            <LoraModelCard
              key={model.id}
              model={model}
              selected={selectedModelId === model.id}
              onDelete={() => deleteMutation.mutate(model.id)}
              onClick={() => setSelectedModel(model)}
            />
          ))}
        </div>
      )}

      {/* Train Modal */}
      <TrainLoraModal
        open={showTrainModal}
        onClose={() => setShowTrainModal(false)}
      />

      {/* Upload Modal */}
      <UploadLoraModal
        open={showUploadModal}
        onClose={() => setShowUploadModal(false)}
      />

      </div>
      {!selectedModel && <aside className="hidden min-[1100px]:block sticky top-4 w-[340px] shrink-0 rounded-lg border border-border bg-chrome p-5 text-sm text-muted-foreground">Select a model to view training details, evaluations, and actions.</aside>}
      {/* Model inspector */}
      {selectedModel && (
        <aside aria-label="Model inspector" className="fixed inset-0 z-40 overflow-y-auto bg-chrome p-5 min-[1100px]:sticky min-[1100px]:top-4 min-[1100px]:z-auto min-[1100px]:max-h-[calc(100vh-120px)] min-[1100px]:w-[340px] min-[1100px]:shrink-0 min-[1100px]:rounded-lg min-[1100px]:border min-[1100px]:border-border">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">{selectedModel.name}</h3>
                <button
                  onClick={() => setSelectedModel(null)}
                  aria-label="Close model inspector"
                  className="p-1 hover:bg-muted rounded-lg transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <TrainingProgress model={selectedModel} />
              <div className="space-y-3 text-sm">
                <section className="rounded-md border border-border p-3">
                  <h4 className="font-medium">Usage</h4>
                  <p className="text-muted-foreground">{usageError ? 'Usage unavailable' : usage ? `${usage.total} generated images` : 'Loading usage…'}</p>
                </section>
                <section className="rounded-md border border-border p-3">
                  <h4 className="font-medium">Latest evaluation</h4>
                  {selectedModel.latest_evaluation ? <Link className="text-sm hover:underline" href={`/models/${selectedModel.id}/evaluations/${selectedModel.latest_evaluation.id}`}>
                    {selectedModel.latest_evaluation.status}{selectedModel.latest_evaluation.overall_score != null ? ` · ${selectedModel.latest_evaluation.overall_score.toFixed(1)}/10` : ''} — View evaluation
                  </Link> : <p className="text-muted-foreground">No evaluations yet</p>}
                </section>
                <div className="grid grid-cols-2 gap-3">
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

                {selectedModel.source_preview_images?.filter((p) => p.thumbnail_uri_small).length > 0 && (
                  <div>
                    <span className="text-muted-foreground text-sm">Sample Training Images</span>
                    <div className="flex gap-2 mt-1.5">
                      {selectedModel.source_preview_images
                        .filter((p) => p.thumbnail_uri_small)
                        .map((img) => (
                          <div key={img.id} className="w-16 h-16 rounded-lg overflow-hidden bg-muted">
                            <img
                              src={imagesApi.getThumbnailUrl(img.thumbnail_uri_small!.split('/').pop()!)}
                              alt=""
                              className="w-full h-full object-cover"
                            />
                          </div>
                        ))}
                    </div>
                  </div>
                )}

                {selectedModel.training_config && (
                  <div>
                    <span className="text-muted-foreground">Training Config</span>
                    <pre className="mt-1 bg-muted/50 p-2 rounded text-xs overflow-x-auto">
                      {JSON.stringify(selectedModel.training_config, null, 2)}
                    </pre>
                  </div>
                )}

                {/* Weights storage status */}
                {isModelReady(selectedModel) && (
                  <div>
                    <span className="text-muted-foreground">Weights Storage</span>
                    {selectedModel.has_local_weights ? (
                      <div className="mt-1 flex items-center justify-between p-2 bg-emerald-50 dark:bg-emerald-950/30 rounded-lg">
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
                          <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
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

              {isModelReady(selectedModel) && (
                <div className="flex flex-wrap gap-2 pt-2">
                  {selectedModel.has_local_weights && (
                    <a
                      href={generationApi.getLoraWeightsUrl(selectedModel.id)}
                      download
                      className="flex items-center gap-2 px-4 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-colors"
                    >
                      <Download className="h-4 w-4" />
                      Download
                    </a>
                  )}
                  <Link
                    href={`/models/${selectedModel.id}/evaluate`}
                    className="flex items-center gap-2 px-4 py-2 text-sm bg-amber-600 text-white rounded-lg hover:bg-amber-700 transition-colors"
                  >
                    <FlaskConical className="h-4 w-4" />
                    Evaluate
                  </Link>
                  <Link
                    href={`/generate?lora=${selectedModel.id}`}
                    className="flex items-center gap-2 px-4 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
                  >
                    <Sparkles className="h-4 w-4" />
                    Create with it
                  </Link>
                </div>
              )}
              <div className="flex flex-wrap gap-2 border-t border-border pt-3 text-sm">
                {selectedModel.status === 'training' && <button disabled={recoverMutation.isPending} onClick={() => recoverMutation.mutate(selectedModel.id)} className="rounded-md border border-input px-3 py-2 disabled:opacity-50">Recover training</button>}
                {selectedModel.status === 'failed' && <button disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(selectedModel.id)} className="rounded-md border border-input px-3 py-2 disabled:opacity-50">Retry training</button>}
                <button onClick={() => { if (confirm(`Delete model “${selectedModel.name}”?`)) { deleteMutation.mutate(selectedModel.id); setSelectedModel(null); } }} className="rounded-md px-3 py-2 text-danger hover:bg-danger/10">Delete model</button>
              </div>
            </div>
        </aside>
      )}
    </div>
  );
}
