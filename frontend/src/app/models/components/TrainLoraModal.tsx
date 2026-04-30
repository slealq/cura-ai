'use client';

import { useState, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { generationApi, foldersApi, clustersApi, settingsApi, billingApi } from '@/lib/api';
import { X, Zap } from 'lucide-react';
import { toast } from 'sonner';
import { trackFunnelStep } from '@/lib/observability';
import ModelSelector from '@/components/ModelSelector';
import FluxTrainForm, { type FluxTrainData } from './FluxTrainForm';
import QwenTrainForm, { type QwenTrainData } from './QwenTrainForm';

const BASE_MODELS = [
  { value: 'flux-dev', label: 'Flux' },
  { value: 'qwen-2.5', label: 'Qwen 2.5' },
];

interface TrainLoraModalProps {
  open: boolean;
  onClose: () => void;
}

export default function TrainLoraModal({ open, onClose }: TrainLoraModalProps) {
  const queryClient = useQueryClient();
  const hasInitialized = useRef(false);
  const [baseModel, setBaseModel] = useState('flux-dev');

  // Fetch settings defaults
  const { data: baseModelData } = useQuery({
    queryKey: ['base-model'],
    queryFn: settingsApi.getBaseModel,
    enabled: open,
  });

  const { data: trainConfig } = useQuery({
    queryKey: ['training-config', baseModel],
    queryFn: () => settingsApi.getTrainingConfig(baseModel),
    enabled: open,
  });

  // Fetch folders + clusters for source selectors
  const { data: foldersData } = useQuery({
    queryKey: ['folders'],
    queryFn: () => foldersApi.list({ limit: 200 }),
    enabled: open,
  });

  const { data: clustersData } = useQuery({
    queryKey: ['clusters'],
    queryFn: () => clustersApi.list({ limit: 200 }),
    enabled: open,
  });

  // Fetch training costs
  const { data: trainingCosts } = useQuery({
    queryKey: ['training-costs'],
    queryFn: billingApi.getTrainingCosts,
    enabled: open,
  });

  // Initialize base model from settings
  useEffect(() => {
    if (baseModelData && !hasInitialized.current) {
      hasInitialized.current = true;
      if (BASE_MODELS.some((m) => m.value === baseModelData.base_model)) {
        setBaseModel(baseModelData.base_model);
      }
    }
  }, [baseModelData]);

  // Reset init flag when modal closes
  useEffect(() => {
    if (!open) {
      hasInitialized.current = false;
    }
  }, [open]);

  // Train mutation
  const trainMutation = useMutation({
    mutationFn: generationApi.trainLora,
    onSuccess: (data) => {
      trackFunnelStep('training', 'train_started', { jobId: data.job_id, baseModel });
      toast.success(`Training started! Job #${data.job_id}`);
      queryClient.invalidateQueries({ queryKey: ['lora-models'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      onClose();
    },
    onError: (err: Error) => {
      toast.error(`Failed to start training: ${err.message}`);
    },
  });

  const handleFluxSubmit = (data: FluxTrainData) => {
    trackFunnelStep('training', 'config_saved', { baseModel, source: data.folder_id ? 'folder' : 'cluster' });
    trainMutation.mutate(data);
  };

  const handleQwenSubmit = (data: QwenTrainData) => {
    trackFunnelStep('training', 'config_saved', { baseModel, source: data.folder_id ? 'folder' : 'cluster' });
    trainMutation.mutate(data);
  };

  if (!open) return null;

  const folders = foldersData?.items || [];
  const clusterItems = clustersData?.items || [];
  const defaultSteps = trainConfig?.steps ?? (baseModel === 'qwen-2.5' ? 2000 : 1000);
  const defaultIsStyle = trainConfig?.is_style ?? false;
  const defaultLearningRate = trainConfig?.learning_rate ?? 0.0005;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/50 z-50"
        onClick={onClose}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="bg-card rounded-xl shadow-xl max-w-md w-full max-h-[90vh] overflow-y-auto p-6 space-y-4"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">Train New LoRA</h3>
            <button
              onClick={onClose}
              className="p-1 hover:bg-muted rounded-lg transition-colors"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Base Model */}
          <div>
            <ModelSelector
              label="Base Model *"
              models={BASE_MODELS}
              value={baseModel}
              onChange={(v) => setBaseModel(v)}
              size="sm"
            />
            {trainingCosts?.costs[baseModel] != null && trainingCosts.costs[baseModel] > 0 && (
              <span className="inline-flex items-center gap-0.5 text-xs text-amber-600 dark:text-amber-400 mt-1.5">
                <Zap className="h-3 w-3" />
                ~{trainingCosts.costs[baseModel]} sparks per training run
              </span>
            )}
          </div>

          {/* Model-specific form */}
          {baseModel === 'flux-dev' ? (
            <FluxTrainForm
              defaultSteps={defaultSteps}
              defaultIsStyle={defaultIsStyle}
              folders={folders}
              clusters={clusterItems}
              isPending={trainMutation.isPending}
              onSubmit={handleFluxSubmit}
              onCancel={onClose}
            />
          ) : (
            <QwenTrainForm
              defaultSteps={baseModel === 'qwen-2.5' ? Math.max(defaultSteps, 2000) : defaultSteps}
              defaultLearningRate={defaultLearningRate}
              folders={folders}
              clusters={clusterItems}
              isPending={trainMutation.isPending}
              onSubmit={handleQwenSubmit}
              onCancel={onClose}
            />
          )}
        </div>
      </div>
    </>
  );
}
