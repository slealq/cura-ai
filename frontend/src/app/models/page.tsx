'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { generationApi } from '@/lib/api';
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
} from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import { cn, formatDate } from '@/lib/utils';
import type { LoraModel } from '@/types';
import { imagesApi } from '@/lib/api';
import TrainLoraModal from './components/TrainLoraModal';

const BASE_MODELS = [
  { value: 'flux-dev', label: 'Flux' },
  { value: 'qwen-2.5', label: 'Qwen 2.5' },
];

const baseModelBadge: Record<string, string> = {
  'flux-dev': 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300',
  'qwen-2.5': 'bg-orange-100 text-orange-700 dark:bg-orange-900/50 dark:text-orange-300',
};

const statusConfig: Record<string, { icon: typeof Clock; color: string; label: string }> = {
  pending: { icon: Clock, color: 'text-gray-500 bg-gray-100 dark:bg-gray-900/50 dark:text-gray-400', label: 'Pending' },
  training: { icon: Loader2, color: 'text-blue-600 bg-blue-100 dark:bg-blue-900/50 dark:text-blue-300', label: 'Training' },
  completed: { icon: CheckCircle, color: 'text-green-600 bg-green-100 dark:bg-green-900/50 dark:text-green-300', label: 'Completed' },
  failed: { icon: XCircle, color: 'text-red-600 bg-red-100 dark:bg-red-900/50 dark:text-red-300', label: 'Failed' },
  archived: { icon: Archive, color: 'text-gray-500 bg-gray-100 dark:bg-gray-900/50 dark:text-gray-400', label: 'Archived' },
};

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
}: {
  model: LoraModel;
  onDelete: () => void;
  onClick: () => void;
}) {
  const config = statusConfig[model.status] || statusConfig.pending;
  const StatusIcon = config.icon;
  const sourceInfo = getSourceInfo(model);
  const previews = model.source_preview_images?.filter((p) => p.thumbnail_uri_small) || [];

  return (
    <div
      className="bg-card border border-border rounded-xl overflow-hidden hover:shadow-md transition-shadow cursor-pointer"
      onClick={onClick}
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
            <p className="text-xs text-muted-foreground mt-0.5">
              Trigger: <code className="bg-muted px-1 py-0.5 rounded">{model.trigger_word}</code>
            </p>
          </div>

          <span className={cn('flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium', config.color)}>
            <StatusIcon className={cn('h-3 w-3', model.status === 'training' && 'animate-spin')} />
            {config.label}
          </span>
        </div>

        <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground items-center">
          <span>{model.training_images_count} images</span>
          <span className={cn('px-1.5 py-0.5 rounded-full text-[10px] font-semibold', baseModelBadge[model.base_model] || 'bg-gray-100 text-gray-700 dark:bg-gray-900/50 dark:text-gray-300')}>
            {BASE_MODELS.find((m) => m.value === model.base_model)?.label || model.base_model}
          </span>
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

        {/* Evaluation info */}
        {model.status === 'completed' && (
          <div className="mt-3">
            {model.latest_evaluation ? (
              <Link
                href={`/models/${model.id}/evaluations/${model.latest_evaluation.id}`}
                onClick={(e) => e.stopPropagation()}
                className="flex items-center gap-2 text-xs px-2.5 py-1.5 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
              >
                <FlaskConical className="h-3 w-3 text-amber-600 flex-shrink-0" />
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
                  <span className="text-red-600 dark:text-red-400">Evaluation failed</span>
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
          <p className="mt-2 text-xs text-red-600 dark:text-red-400 line-clamp-1">{model.error_message}</p>
        )}

        <div className="mt-3 flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground">
            {formatDate(model.created_at)}
          </span>
          <div className="flex items-center gap-1">
            {model.status === 'completed' && (
              <>
                <Link
                  href={`/models/${model.id}/evaluate`}
                  onClick={(e) => e.stopPropagation()}
                  className="p-1.5 hover:bg-muted rounded-lg transition-colors text-amber-600"
                  title="Evaluate model quality"
                >
                  <FlaskConical className="h-4 w-4" />
                </Link>
                <Link
                  href={`/generate?lora=${model.id}`}
                  onClick={(e) => e.stopPropagation()}
                  className="p-1.5 hover:bg-muted rounded-lg transition-colors text-purple-600"
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
              className="p-1.5 hover:bg-red-50 rounded-lg transition-colors text-muted-foreground hover:text-red-600"
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
  const [selectedModel, setSelectedModel] = useState<LoraModel | null>(null);

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
      <TrainLoraModal
        open={showTrainModal}
        onClose={() => setShowTrainModal(false)}
      />

      {/* Detail Modal */}
      {selectedModel && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => setSelectedModel(null)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-card rounded-xl shadow-xl max-w-lg w-full p-6 space-y-4"
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

                {selectedModel.error_message && (
                  <div className="p-3 bg-red-50 rounded-lg">
                    <span className="text-red-700 font-medium">Error:</span>
                    <p className="text-red-600 mt-0.5">{selectedModel.error_message}</p>
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

              {selectedModel.status === 'completed' && (
                <div className="flex gap-2 pt-2">
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
                    Generate
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
