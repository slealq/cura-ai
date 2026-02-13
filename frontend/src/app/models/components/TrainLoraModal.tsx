'use client';

import { useState, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { generationApi, foldersApi, clustersApi, settingsApi } from '@/lib/api';
import { X } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
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
    trainMutation.mutate(data);
  };

  const handleQwenSubmit = (data: QwenTrainData) => {
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

          {/* Base Model Toggle */}
          <div>
            <label className="block text-sm font-medium mb-1">Base Model *</label>
            <div className="flex rounded-lg border border-border overflow-hidden">
              {BASE_MODELS.map((m) => (
                <button
                  key={m.value}
                  onClick={() => setBaseModel(m.value)}
                  className={cn(
                    'flex-1 px-3 py-1.5 text-sm font-medium transition-colors',
                    baseModel === m.value
                      ? 'bg-primary text-primary-foreground'
                      : 'hover:bg-muted'
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>
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
