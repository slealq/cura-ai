'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { generationApi, foldersApi, clustersApi } from '@/lib/api';
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
} from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import { cn } from '@/lib/utils';
import type { LoraModel } from '@/types';

const statusConfig: Record<string, { icon: typeof Clock; color: string; label: string }> = {
  pending: { icon: Clock, color: 'text-gray-500 bg-gray-100', label: 'Pending' },
  training: { icon: Loader2, color: 'text-blue-600 bg-blue-100', label: 'Training' },
  completed: { icon: CheckCircle, color: 'text-green-600 bg-green-100', label: 'Completed' },
  failed: { icon: XCircle, color: 'text-red-600 bg-red-100', label: 'Failed' },
  archived: { icon: Archive, color: 'text-gray-500 bg-gray-100', label: 'Archived' },
};

function getSourceLabel(model: LoraModel): string | null {
  if (model.folder_name) return `folder "${model.folder_name}"`;
  if (model.cluster_name) return `cluster "${model.cluster_name}"`;
  return null;
}

function LoraModelCard({
  model,
  onDelete,
  onClick,
}: {
  model: LoraModel;
  onDelete: () => void;
  onClick: () => void;
}) {
  const config = statusConfig[model.status] || statusConfig.pending;
  const StatusIcon = config.icon;
  const sourceLabel = getSourceLabel(model);

  return (
    <div
      className="bg-white border border-border rounded-xl p-5 hover:shadow-md transition-shadow cursor-pointer"
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-purple-50 rounded-lg">
            <Box className="h-5 w-5 text-purple-600" />
          </div>
          <div>
            <h3 className="font-semibold text-sm">{model.name}</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Trigger: <code className="bg-muted px-1 py-0.5 rounded">{model.trigger_word}</code>
            </p>
          </div>
        </div>

        <span className={cn('flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium', config.color)}>
          <StatusIcon className={cn('h-3 w-3', model.status === 'training' && 'animate-spin')} />
          {config.label}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap gap-3 text-xs text-muted-foreground">
        <span>{model.training_images_count} images</span>
        <span>{model.base_model}</span>
        {sourceLabel && <span>from {sourceLabel}</span>}
      </div>

      {model.error_message && (
        <p className="mt-2 text-xs text-red-600 line-clamp-1">{model.error_message}</p>
      )}

      <div className="mt-3 flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">
          {new Date(model.created_at).toLocaleDateString()}
        </span>
        <div className="flex items-center gap-1">
          {model.status === 'completed' && (
            <Link
              href={`/generate?lora=${model.id}`}
              onClick={(e) => e.stopPropagation()}
              className="p-1.5 hover:bg-muted rounded-lg transition-colors text-purple-600"
              title="Generate with this LoRA"
            >
              <Sparkles className="h-4 w-4" />
            </Link>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="p-1.5 hover:bg-red-50 rounded-lg transition-colors text-muted-foreground hover:text-red-600"
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

type SourceType = 'folder' | 'cluster';

export default function ModelsPage() {
  const queryClient = useQueryClient();
  const [showTrainModal, setShowTrainModal] = useState(false);
  const [selectedModel, setSelectedModel] = useState<LoraModel | null>(null);

  // Form state for training
  const [trainName, setTrainName] = useState('');
  const [trainTrigger, setTrainTrigger] = useState('');
  const [sourceType, setSourceType] = useState<SourceType>('folder');
  const [trainFolderId, setTrainFolderId] = useState<number | undefined>(undefined);
  const [trainClusterId, setTrainClusterId] = useState<number | undefined>(undefined);
  const [trainSteps, setTrainSteps] = useState(1000);
  const [trainIsStyle, setTrainIsStyle] = useState(false);
  const [trainUseCaptions, setTrainUseCaptions] = useState(false);
  const [trainCaptionTags, setTrainCaptionTags] = useState(true);
  const [trainCaptionDescription, setTrainCaptionDescription] = useState(true);

  // Fetch LoRA models
  const { data: loraData, isLoading } = useQuery({
    queryKey: ['lora-models'],
    queryFn: () => generationApi.listLora(),
    refetchInterval: 5000,
  });

  // Fetch folders for dropdown
  const { data: foldersData } = useQuery({
    queryKey: ['folders'],
    queryFn: () => foldersApi.list({ limit: 200 }),
  });

  // Fetch clusters for dropdown
  const { data: clustersData } = useQuery({
    queryKey: ['clusters'],
    queryFn: () => clustersApi.list({ limit: 200 }),
  });

  // Train mutation
  const trainMutation = useMutation({
    mutationFn: generationApi.trainLora,
    onSuccess: (data) => {
      toast.success(`Training started! Job #${data.job_id}`);
      queryClient.invalidateQueries({ queryKey: ['lora-models'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      setShowTrainModal(false);
      resetForm();
    },
    onError: (err: Error) => {
      toast.error(`Failed to start training: ${err.message}`);
    },
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

  const resetForm = () => {
    setTrainName('');
    setTrainTrigger('');
    setSourceType('folder');
    setTrainFolderId(undefined);
    setTrainClusterId(undefined);
    setTrainSteps(1000);
    setTrainIsStyle(false);
    setTrainUseCaptions(false);
    setTrainCaptionTags(true);
    setTrainCaptionDescription(true);
  };

  const hasValidSource = sourceType === 'folder' ? !!trainFolderId : !!trainClusterId;

  const handleTrain = () => {
    if (!trainName.trim() || !trainTrigger.trim() || !hasValidSource) {
      toast.error('Please fill in all required fields');
      return;
    }
    trainMutation.mutate({
      name: trainName.trim(),
      trigger_word: trainTrigger.trim(),
      ...(sourceType === 'folder'
        ? { folder_id: trainFolderId }
        : { cluster_id: trainClusterId }),
      steps: trainSteps,
      is_style: trainIsStyle,
      use_captions: trainUseCaptions,
      caption_include_tags: trainCaptionTags,
      caption_include_description: trainCaptionDescription,
    });
  };

  const models = loraData?.items || [];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">LoRA Models</h1>
          <p className="text-muted-foreground mt-1">
            Train and manage LoRA adapters for image generation
          </p>
        </div>
        <button
          onClick={() => setShowTrainModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors font-medium text-sm"
        >
          <Plus className="h-4 w-4" />
          Train New LoRA
        </button>
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
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {models.map((model) => (
            <LoraModelCard
              key={model.id}
              model={model}
              onDelete={() => deleteMutation.mutate(model.id)}
              onClick={() => setSelectedModel(model)}
            />
          ))}
        </div>
      )}

      {/* Train Modal */}
      {showTrainModal && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => setShowTrainModal(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-white rounded-xl shadow-xl max-w-md w-full p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">Train New LoRA</h3>
                <button
                  onClick={() => setShowTrainModal(false)}
                  className="p-1 hover:bg-muted rounded-lg transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium mb-1">Name *</label>
                  <input
                    type="text"
                    value={trainName}
                    onChange={(e) => setTrainName(e.target.value)}
                    placeholder="My LoRA Model"
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Trigger Word *</label>
                  <input
                    type="text"
                    value={trainTrigger}
                    onChange={(e) => setTrainTrigger(e.target.value)}
                    placeholder="e.g. TOK, MYSTYLE"
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Use this word in your prompts to activate the LoRA
                  </p>
                </div>

                {/* Source Type Toggle */}
                <div>
                  <label className="block text-sm font-medium mb-1">Source *</label>
                  <div className="flex rounded-lg border border-border overflow-hidden mb-2">
                    <button
                      onClick={() => {
                        setSourceType('folder');
                        setTrainClusterId(undefined);
                      }}
                      className={cn(
                        'flex-1 px-3 py-1.5 text-sm font-medium transition-colors',
                        sourceType === 'folder'
                          ? 'bg-primary text-primary-foreground'
                          : 'hover:bg-muted'
                      )}
                    >
                      Folder
                    </button>
                    <button
                      onClick={() => {
                        setSourceType('cluster');
                        setTrainFolderId(undefined);
                      }}
                      className={cn(
                        'flex-1 px-3 py-1.5 text-sm font-medium transition-colors',
                        sourceType === 'cluster'
                          ? 'bg-primary text-primary-foreground'
                          : 'hover:bg-muted'
                      )}
                    >
                      Cluster
                    </button>
                  </div>

                  {sourceType === 'folder' ? (
                    <select
                      value={trainFolderId ?? ''}
                      onChange={(e) => setTrainFolderId(e.target.value ? parseInt(e.target.value) : undefined)}
                      className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                    >
                      <option value="">Select a folder...</option>
                      {foldersData?.items.map((folder) => (
                        <option key={folder.id} value={folder.id}>
                          {folder.name} ({folder.image_count} images)
                        </option>
                      ))}
                    </select>
                  ) : (
                    <select
                      value={trainClusterId ?? ''}
                      onChange={(e) => setTrainClusterId(e.target.value ? parseInt(e.target.value) : undefined)}
                      className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                    >
                      <option value="">Select a cluster...</option>
                      {clustersData?.items.map((cluster) => (
                        <option key={cluster.id} value={cluster.id}>
                          {cluster.display_name || cluster.summary_title || `Cluster ${cluster.id}`} ({cluster.size} images)
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">
                    Training Steps: {trainSteps}
                  </label>
                  <input
                    type="range"
                    min={100}
                    max={4000}
                    step={100}
                    value={trainSteps}
                    onChange={(e) => setTrainSteps(parseInt(e.target.value))}
                    className="w-full"
                  />
                  <div className="flex justify-between text-[10px] text-muted-foreground">
                    <span>100</span>
                    <span>4000</span>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setTrainIsStyle(!trainIsStyle)}
                    className={cn(
                      'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors',
                      trainIsStyle ? 'bg-primary' : 'bg-gray-300'
                    )}
                  >
                    <span
                      className={cn(
                        'inline-block h-4 w-4 transform rounded-full bg-white transition-transform mt-0.5',
                        trainIsStyle ? 'translate-x-4 ml-0.5' : 'translate-x-0.5'
                      )}
                    />
                  </button>
                  <span className="text-sm">Style mode</span>
                  <span className="text-xs text-muted-foreground">
                    (for artistic styles rather than subjects)
                  </span>
                </div>

                {/* Per-Image Captions */}
                <div className="border-t border-border pt-3">
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => setTrainUseCaptions(!trainUseCaptions)}
                      className={cn(
                        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors',
                        trainUseCaptions ? 'bg-primary' : 'bg-gray-300'
                      )}
                    >
                      <span
                        className={cn(
                          'inline-block h-4 w-4 transform rounded-full bg-white transition-transform mt-0.5',
                          trainUseCaptions ? 'translate-x-4 ml-0.5' : 'translate-x-0.5'
                        )}
                      />
                    </button>
                    <span className="text-sm">Per-image captions</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1.5 ml-12">
                    Include generated tags and descriptions as captions for each training image
                  </p>

                  {trainUseCaptions && (
                    <div className="mt-3 ml-12 space-y-2">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={trainCaptionTags}
                          onChange={(e) => setTrainCaptionTags(e.target.checked)}
                          className="rounded border-gray-300"
                        />
                        <span className="text-sm">Include tags</span>
                      </label>
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={trainCaptionDescription}
                          onChange={(e) => setTrainCaptionDescription(e.target.checked)}
                          className="rounded border-gray-300"
                        />
                        <span className="text-sm">Include description</span>
                      </label>
                      {!trainCaptionTags && !trainCaptionDescription && (
                        <p className="text-xs text-red-500">
                          At least one caption source must be selected
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex gap-2 justify-end pt-2">
                <button
                  onClick={() => setShowTrainModal(false)}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleTrain}
                  disabled={trainMutation.isPending || !trainName.trim() || !trainTrigger.trim() || !hasValidSource || (trainUseCaptions && !trainCaptionTags && !trainCaptionDescription)}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {trainMutation.isPending ? 'Starting...' : 'Start Training'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Detail Modal */}
      {selectedModel && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => setSelectedModel(null)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-white rounded-xl shadow-xl max-w-lg w-full p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">{selectedModel.name}</h3>
                <button
                  onClick={() => setSelectedModel(null)}
                  className="p-1 hover:bg-muted rounded-lg transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="space-y-3 text-sm">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <span className="text-muted-foreground">Status</span>
                    <p className="font-medium">{selectedModel.status}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Trigger Word</span>
                    <p><code className="bg-muted px-1.5 py-0.5 rounded">{selectedModel.trigger_word}</code></p>
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
                    <p>
                      {selectedModel.folder_name
                        ? `Folder: ${selectedModel.folder_name}`
                        : selectedModel.cluster_name
                          ? `Cluster: ${selectedModel.cluster_name}`
                          : 'N/A'}
                    </p>
                  </div>
                </div>

                {selectedModel.training_config && (
                  <div>
                    <span className="text-muted-foreground">Training Config</span>
                    <pre className="mt-1 bg-muted/50 p-2 rounded text-xs overflow-x-auto">
                      {JSON.stringify(selectedModel.training_config, null, 2)}
                    </pre>
                  </div>
                )}

                {selectedModel.error_message && (
                  <div className="p-3 bg-red-50 rounded-lg">
                    <span className="text-red-700 font-medium">Error:</span>
                    <p className="text-red-600 mt-0.5">{selectedModel.error_message}</p>
                  </div>
                )}

                <div className="text-xs text-muted-foreground space-y-1">
                  <p>Created: {new Date(selectedModel.created_at).toLocaleString()}</p>
                  {selectedModel.training_started_at && (
                    <p>Training started: {new Date(selectedModel.training_started_at).toLocaleString()}</p>
                  )}
                  {selectedModel.training_completed_at && (
                    <p>Training completed: {new Date(selectedModel.training_completed_at).toLocaleString()}</p>
                  )}
                </div>
              </div>

              {selectedModel.status === 'completed' && (
                <div className="flex gap-2 pt-2">
                  <Link
                    href={`/generate?lora=${selectedModel.id}`}
                    className="flex items-center gap-2 px-4 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
                  >
                    <Sparkles className="h-4 w-4" />
                    Generate with this LoRA
                  </Link>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
