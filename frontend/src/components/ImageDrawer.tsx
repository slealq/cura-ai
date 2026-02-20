'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, ExternalLink, RefreshCw, FolderOpen, Zap, ChevronDown, ChevronUp } from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import type { Image, PromptPreset } from '@/types';
import { imagesApi, jobsApi, settingsApi, billingApi } from '@/lib/api';
import { cn, formatDate, formatFileSize } from '@/lib/utils';
import ImageCard from './ImageCard';
import ModelSelector from './ModelSelector';
import PipelineProgress from './PipelineProgress';
import { Slider } from './Slider';

const VISION_MODELS = [
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini', provider: 'openai' },
  { value: 'gpt-4o', label: 'GPT-4o', provider: 'openai' },
  { value: 'gpt-5-mini', label: 'GPT-5 Mini', provider: 'openai' },
  { value: 'gpt-5.2', label: 'GPT-5.2', provider: 'openai' },
  { value: 'claude-3-haiku-20240307', label: 'Claude Haiku 3', provider: 'anthropic' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5', provider: 'anthropic' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6', provider: 'anthropic' },
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6', provider: 'anthropic' },
  { value: 'x-ai/grok-4-fast', label: 'Grok 4 Fast', provider: 'fal' },
  { value: 'qwen/qwen3-vl-235b-a22b-instruct', label: 'Qwen3 VL 235B', provider: 'fal' },
  { value: 'google/gemini-2.5-flash', label: 'Gemini 2.5 Flash', provider: 'fal' },
];

interface ImageDrawerProps {
  image: Image;
  onClose: () => void;
}

export default function ImageDrawer({ image, onClose }: ImageDrawerProps) {
  const queryClient = useQueryClient();
  const hasInitModel = useRef(false);
  const [showDescribeDialog, setShowDescribeDialog] = useState(false);
  const [descriptionPrompt, setDescriptionPrompt] = useState('');
  const [tagPrompt, setTagPrompt] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [staleSteps, setStaleSteps] = useState<string[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [temperature, setTemperature] = useState<number | null>(null);
  const [maxTokensTag, setMaxTokensTag] = useState<number | null>(null);
  const [maxTokensDescribe, setMaxTokensDescribe] = useState<number | null>(null);

  // Live image data — polls every 3s while processing
  const { data: liveImage } = useQuery({
    queryKey: ['images', image.id],
    queryFn: () => imagesApi.get(image.id),
    refetchInterval: isProcessing ? 3000 : false,
    initialData: image,
  });

  // Active jobs for this image — polls while processing
  const { data: imageJobs } = useQuery({
    queryKey: ['jobs', 'image', image.id],
    queryFn: () => jobsApi.listByImage(image.id),
    refetchInterval: isProcessing ? 3000 : false,
    enabled: isProcessing,
  });

  // Detect completion from job polling
  useEffect(() => {
    if (!isProcessing || !imageJobs) return;

    const activeJobs = imageJobs.items.filter(
      (j) => j.status === 'pending' || j.status === 'running'
    );

    if (activeJobs.length === 0 && imageJobs.items.length > 0) {
      const failedJobs = imageJobs.items.filter((j) => j.status === 'failed');
      if (failedJobs.length > 0) {
        toast.error('Processing failed', {
          description: failedJobs[0].error_message || 'An error occurred',
        });
      } else {
        toast.success('Processing complete');
      }
      setIsProcessing(false);
      setStaleSteps([]);
      queryClient.invalidateQueries({ queryKey: ['images'] });
      queryClient.invalidateQueries({ queryKey: ['images', image.id] });
    }
  }, [imageJobs, isProcessing, image.id, queryClient]);

  const { data: similarImages } = useQuery({
    queryKey: ['similar-images', image.id],
    queryFn: () => imagesApi.getSimilar(image.id, 6),
    enabled:
      liveImage.status === 'embedded' || liveImage.status === 'clustered',
  });

  const { data: imageFolders } = useQuery({
    queryKey: ['image-folders', image.id],
    queryFn: () => imagesApi.getFolders(image.id),
  });

  const { data: defaultPrompts } = useQuery({
    queryKey: ['prompt-settings'],
    queryFn: settingsApi.getPrompts,
  });

  const { data: presets } = useQuery({
    queryKey: ['presets'],
    queryFn: settingsApi.listPresets,
  });

  // Provider config for settings-driven model default
  const { data: providerConfig } = useQuery({
    queryKey: ['provider-config'],
    queryFn: settingsApi.getProviderConfig,
  });

  // Vision costs
  const { data: visionCosts } = useQuery({
    queryKey: ['vision-costs'],
    queryFn: billingApi.getVisionCosts,
  });

  // Initialize selectedModel from provider config
  useEffect(() => {
    if (providerConfig && !hasInitModel.current) {
      hasInitModel.current = true;
      const provider = providerConfig.vision_provider;
      const modelId = provider === 'openai'
        ? providerConfig.openai_vision_model
        : provider === 'anthropic'
          ? providerConfig.anthropic_vision_model
          : providerConfig.fal_vision_model;
      if (VISION_MODELS.some((m) => m.value === modelId)) {
        setSelectedModel(modelId);
      } else {
        setSelectedModel(VISION_MODELS[0].value);
      }
    }
  }, [providerConfig]);

  const reprocessMutation = useMutation({
    mutationFn: (options: {
      tag_prompt?: string;
      description_prompt?: string;
      provider?: string;
      model?: string;
      temperature?: number;
      max_tokens_tag?: number;
      max_tokens_describe?: number;
    }) => imagesApi.reprocess(image.id, options),
    onSuccess: (data) => {
      toast.success('Describe started', { description: `Job #${data.job_id}` });
      setIsProcessing(true);
      setStaleSteps([]);
      setShowDescribeDialog(false);
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Failed to start describe'),
  });

  // Initialize prompts from defaults when dialog opens
  const initPrompts = useCallback(() => {
    if (defaultPrompts) {
      setDescriptionPrompt(defaultPrompts.description_prompt);
      setTagPrompt(defaultPrompts.tag_prompt);
    }
    // Reset model to configured default
    if (providerConfig) {
      const provider = providerConfig.vision_provider;
      const modelId = provider === 'openai'
        ? providerConfig.openai_vision_model
        : provider === 'anthropic'
          ? providerConfig.anthropic_vision_model
          : providerConfig.fal_vision_model;
      if (VISION_MODELS.some((m) => m.value === modelId)) {
        setSelectedModel(modelId);
      } else {
        setSelectedModel(VISION_MODELS[0].value);
      }
      // Init advanced params from settings
      setTemperature(providerConfig.vision_temperature ?? 1.0);
      setMaxTokensTag(providerConfig.max_tokens_tagging ?? 1000);
      setMaxTokensDescribe(providerConfig.max_tokens_description ?? 3000);
    }
    setShowAdvanced(false);
  }, [defaultPrompts, providerConfig]);

  useEffect(() => {
    if (showDescribeDialog) {
      initPrompts();
    }
  }, [showDescribeDialog, initPrompts]);

  // Close on escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showDescribeDialog) setShowDescribeDialog(false);
        else onClose();
      }
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose, showDescribeDialog]);

  const getModelParams = () => {
    const m = VISION_MODELS.find((v) => v.value === selectedModel);
    return {
      provider: m?.provider,
      model: selectedModel,
    };
  };

  // Compute cost for describe (tag + describe + embed)
  const getDescribeCost = (): number | null => {
    if (!visionCosts || !selectedModel) return null;
    const m = VISION_MODELS.find((v) => v.value === selectedModel);
    if (!m?.provider) return null;
    const provCosts = visionCosts.costs[m.provider];
    if (!provCosts) return null;
    const modelCosts = provCosts[selectedModel];
    if (!modelCosts) return null;
    return modelCosts.total || ((modelCosts.tag || 0) + (modelCosts.describe || 0));
  };
  const describeCost = getDescribeCost();

  const handleDescribeSubmit = () => {
    reprocessMutation.mutate({
      description_prompt: descriptionPrompt || undefined,
      tag_prompt: tagPrompt || undefined,
      ...getModelParams(),
      temperature: temperature ?? undefined,
      max_tokens_tag: maxTokensTag ?? undefined,
      max_tokens_describe: maxTokensDescribe ?? undefined,
    });
  };

  const imageUrl = imagesApi.getImageUrl(liveImage.object_key);
  const tags = liveImage.metadata?.tags || [];

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed inset-y-0 right-0 w-full max-w-xl bg-card shadow-xl z-50 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-card border-b border-border px-6 py-4 flex items-center justify-between">
          <h2 className="font-semibold truncate">
            {liveImage.original_filename || liveImage.object_key}
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-muted rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Image */}
          <div className="rounded-lg overflow-hidden bg-muted">
            <img
              src={imageUrl}
              alt={liveImage.original_filename || ''}
              className="w-full h-auto"
            />
          </div>

          {/* Pipeline Status */}
          <PipelineProgress
            status={liveImage.status}
            variant="full"
            staleSteps={staleSteps}
          />

          {/* Actions */}
          <div className="flex items-center gap-2 flex-wrap">
            <a
              href={imageUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="p-2 hover:bg-muted rounded-lg transition-colors"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
            <button
              onClick={() => setShowDescribeDialog(true)}
              disabled={isProcessing}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
            >
              <RefreshCw className={cn('h-4 w-4', isProcessing && 'animate-spin')} />
              {isProcessing ? 'Processing...' : 'Describe'}
            </button>
          </div>

          {/* Folders */}
          {imageFolders && imageFolders.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Folders
              </h3>
              <div className="flex flex-wrap gap-1">
                {imageFolders.map((f) => (
                  <Link
                    key={f.id}
                    href={`/images/folder/${f.id}`}
                    onClick={onClose}
                    className="inline-flex items-center gap-1 px-2 py-0.5 bg-muted rounded-full text-xs hover:bg-muted/80 transition-colors"
                  >
                    <FolderOpen className="h-3 w-3" />
                    {f.name}
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* Description */}
          {liveImage.metadata?.description_long && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Description
              </h3>
              <div className="text-sm whitespace-pre-line">
                {liveImage.metadata.description_long}
              </div>
            </div>
          )}

          {/* Tags */}
          {tags.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Tags
              </h3>
              <div className="flex flex-wrap gap-1">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="px-2 py-0.5 bg-muted rounded-full text-xs"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Metadata */}
          <div>
            <h3 className="text-sm font-medium text-muted-foreground mb-2">
              Details
            </h3>
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <dt className="text-muted-foreground">Dimensions</dt>
              <dd>
                {liveImage.width && liveImage.height
                  ? `${liveImage.width} × ${liveImage.height}`
                  : 'N/A'}
              </dd>
              <dt className="text-muted-foreground">File Size</dt>
              <dd>{formatFileSize(liveImage.file_size)}</dd>
              <dt className="text-muted-foreground">Source</dt>
              <dd className="capitalize">
                {liveImage.source.replace('_', ' ')}
              </dd>
              <dt className="text-muted-foreground">Ingested</dt>
              <dd>{formatDate(liveImage.ingested_at)}</dd>
            </dl>
          </div>

          {/* Model Info */}
          {liveImage.metadata && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Processing Info
              </h3>
              <dl className="grid grid-cols-2 gap-2 text-xs">
                {liveImage.metadata.tagging_model && (
                  <>
                    <dt className="text-muted-foreground">Tagging Model</dt>
                    <dd className="font-mono">
                      {liveImage.metadata.tagging_model}
                    </dd>
                  </>
                )}
                {liveImage.metadata.caption_model && (
                  <>
                    <dt className="text-muted-foreground">Description Model</dt>
                    <dd className="font-mono">
                      {liveImage.metadata.caption_model}
                    </dd>
                  </>
                )}
                {liveImage.metadata.embedding_model && (
                  <>
                    <dt className="text-muted-foreground">Embedding Model</dt>
                    <dd className="font-mono">
                      {liveImage.metadata.embedding_model}
                    </dd>
                  </>
                )}
              </dl>
            </div>
          )}

          {/* Similar Images */}
          {similarImages && similarImages.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Similar Images
              </h3>
              <div className="grid grid-cols-3 gap-2">
                {similarImages.map((img) => (
                  <ImageCard key={img.id} image={img} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Describe Dialog */}
      {showDescribeDialog && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => setShowDescribeDialog(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-card rounded-xl shadow-xl max-w-2xl w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold">Describe Image</h3>
              <p className="text-sm text-muted-foreground">
                Tag, describe, and embed this image using the selected vision model.
              </p>

              {presets && presets.length > 0 && (
                <div>
                  <label className="block text-sm font-medium mb-1">Preset</label>
                  <select
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                    value=""
                    onChange={(e) => {
                      const p = presets.find((pr) => pr.id === Number(e.target.value));
                      if (p) {
                        setTagPrompt(p.tag_prompt);
                        setDescriptionPrompt(p.description_prompt);
                      }
                    }}
                  >
                    <option value="" disabled>Load from preset...</option>
                    {presets.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}{p.is_default ? ' (active)' : ''}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <ModelSelector
                label="Model"
                models={VISION_MODELS}
                value={selectedModel}
                onChange={(v) => setSelectedModel(v)}
                size="sm"
              />

              <div>
                <label className="block text-sm font-medium mb-2">
                  Tag Instructions
                </label>
                <textarea
                  value={tagPrompt}
                  onChange={(e) => setTagPrompt(e.target.value)}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm font-mono resize-y min-h-[120px]"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">
                  Description Instructions
                </label>
                <textarea
                  value={descriptionPrompt}
                  onChange={(e) => setDescriptionPrompt(e.target.value)}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm font-mono resize-y min-h-[120px]"
                />
              </div>

              {/* Advanced Parameters */}
              <button
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                Advanced Parameters
              </button>

              {showAdvanced && (
                <div className="border border-border rounded-lg p-4 space-y-3">
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">
                      Temperature: {(temperature ?? 1.0).toFixed(1)}
                    </label>
                    <Slider
                      min={0}
                      max={20}
                      value={Math.round((temperature ?? 1.0) * 10)}
                      onChange={(v) => setTemperature(v / 10)}
                      className="w-full"
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                      <span>0.0</span>
                      <span>2.0</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">
                        Tag Tokens: {maxTokensTag ?? 1000}
                      </label>
                      <Slider
                        min={100}
                        max={4000}
                        step={100}
                        value={maxTokensTag ?? 1000}
                        onChange={(v) => setMaxTokensTag(v)}
                        className="w-full"
                      />
                      <div className="flex justify-between text-[10px] text-muted-foreground">
                        <span>100</span>
                        <span>4000</span>
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">
                        Description Tokens: {maxTokensDescribe ?? 3000}
                      </label>
                      <Slider
                        min={500}
                        max={8000}
                        step={100}
                        value={maxTokensDescribe ?? 3000}
                        onChange={(v) => setMaxTokensDescribe(v)}
                        className="w-full"
                      />
                      <div className="flex justify-between text-[10px] text-muted-foreground">
                        <span>500</span>
                        <span>8000</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div className="flex items-center gap-2 justify-end">
                {describeCost !== null && describeCost > 0 && (
                  <span className="inline-flex items-center gap-0.5 text-xs text-amber-600 dark:text-amber-400 mr-auto">
                    <Zap className="h-3 w-3" />
                    ~{Math.round(describeCost)} sparks
                  </span>
                )}
                <button
                  onClick={() => setShowDescribeDialog(false)}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDescribeSubmit}
                  disabled={reprocessMutation.isPending}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {reprocessMutation.isPending ? 'Starting...' : 'Describe'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
