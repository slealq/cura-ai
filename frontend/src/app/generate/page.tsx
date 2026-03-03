'use client';

import { useState, useEffect, useRef, Suspense } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { generationApi, settingsApi, billingApi } from '@/lib/api';
import { Loader2, Sparkles, ChevronDown, ChevronUp, X, Plus, Trash2, Zap, Wand2 } from 'lucide-react';
import { toast } from 'sonner';
import { trackFunnelStep } from '@/lib/observability';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import GeneratedImageCard from '@/components/GeneratedImageCard';
import ModelSelector from '@/components/ModelSelector';
import { cn } from '@/lib/utils';
import { Slider } from '@/components/Slider';

const SIZE_PRESETS = [
  { label: '1024 x 1024', w: 1024, h: 1024 },
  { label: '768 x 1024', w: 768, h: 1024 },
  { label: '1024 x 768', w: 1024, h: 768 },
  { label: '512 x 512', w: 512, h: 512 },
  { label: '768 x 1344', w: 768, h: 1344 },
  { label: '1344 x 768', w: 1344, h: 768 },
];

const BASE_MODELS = [
  { value: 'nano-banana-pro', label: 'Nano Banana Pro', defaultGuidance: 0, hasLora: false, hasStepsGuidance: false, hasWidthHeight: false, usesResolutionAspect: true, hasSafetyTolerance: true, hasWebSearch: true, hasImageSizePreset: false, hasNegativePrompt: false, maxSafetyLevel: 6, maxImages: 4 },
  { value: 'nano-banana-2', label: 'Nano Banana 2', defaultGuidance: 0, hasLora: false, hasStepsGuidance: false, hasWidthHeight: false, usesResolutionAspect: true, hasSafetyTolerance: true, hasWebSearch: true, hasImageSizePreset: false, hasNegativePrompt: false, maxSafetyLevel: 6, maxImages: 4 },
  { value: 'flux-2-pro', label: 'Flux 2 Pro', defaultGuidance: 0, hasLora: false, hasStepsGuidance: false, hasWidthHeight: false, usesResolutionAspect: false, hasSafetyTolerance: true, hasWebSearch: false, hasImageSizePreset: true, hasNegativePrompt: false, maxSafetyLevel: 5, maxImages: 8 },
  { value: 'flux-dev', label: 'Flux', defaultGuidance: 3.5, hasLora: true, hasStepsGuidance: true, hasWidthHeight: true, usesResolutionAspect: false, hasSafetyTolerance: false, hasWebSearch: false, hasImageSizePreset: false, hasNegativePrompt: true, maxSafetyLevel: 6, maxImages: 8 },
  { value: 'qwen-2.5', label: 'Qwen Image 2512', defaultGuidance: 4.0, hasLora: true, hasStepsGuidance: true, hasWidthHeight: true, usesResolutionAspect: false, hasSafetyTolerance: false, hasWebSearch: false, hasImageSizePreset: false, hasNegativePrompt: true, maxSafetyLevel: 6, maxImages: 8 },
];

const RESOLUTIONS = [
  { value: '0.5K', label: '0.5K' },
  { value: '1K', label: '1K' },
  { value: '2K', label: '2K' },
  { value: '4K', label: '4K' },
];

const ASPECT_RATIOS = [
  { value: '1:1', label: '1:1' },
  { value: '16:9', label: '16:9' },
  { value: '9:16', label: '9:16' },
  { value: '4:3', label: '4:3' },
  { value: '3:4', label: '3:4' },
  { value: '3:2', label: '3:2' },
  { value: '2:3', label: '2:3' },
  { value: '21:9', label: '21:9' },
  { value: '7:4', label: '7:4' },
  { value: '4:7', label: '4:7' },
  { value: '5:4', label: '5:4' },
];

const SAFETY_LEVELS = [
  { value: '1', label: '1 (Strictest)', level: 1 },
  { value: '2', label: '2', level: 2 },
  { value: '3', label: '3', level: 3 },
  { value: '4', label: '4', level: 4 },
  { value: '5', label: '5', level: 5 },
  { value: '6', label: '6 (Most Permissive)', level: 6 },
];

const IMAGE_SIZE_PRESETS = [
  { value: 'square_hd', label: 'Square HD', ratio: '1:1' },
  { value: 'square', label: 'Square', ratio: '1:1' },
  { value: 'landscape_4_3', label: 'Landscape 4:3', ratio: '4:3' },
  { value: 'landscape_16_9', label: 'Landscape 16:9', ratio: '16:9' },
  { value: 'portrait_4_3', label: 'Portrait 3:4', ratio: '3:4' },
  { value: 'portrait_16_9', label: 'Portrait 9:16', ratio: '9:16' },
  { value: 'custom', label: 'Custom', ratio: '1:1' },
] as const;

// Default safety tolerance per model (matches backend FAL_MODEL_CONFIG.default_safety_tolerance)
const DEFAULT_SAFETY_TOLERANCE: Record<string, string> = {
  'nano-banana-pro': '4',
  'nano-banana-2': '4',
  'flux-2-pro': '2',
};

function AspectIcon({ ratio, className }: { ratio: string; className?: string }) {
  const dims: Record<string, [number, number]> = {
    '1:1': [10, 10], '16:9': [14, 8], '9:16': [8, 14],
    '4:3': [12, 9], '3:4': [9, 12],
  };
  const [w, h] = dims[ratio] || [10, 10];
  const x = (16 - w) / 2, y = (16 - h) / 2;
  return (
    <svg viewBox="0 0 16 16" className={cn('w-4 h-4', className)}>
      <rect x={x} y={y} width={w} height={h} rx={1}
        className="fill-current" />
    </svg>
  );
}

export default function GeneratePage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-32"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>}>
      <GeneratePageInner />
    </Suspense>
  );
}

function GeneratePageInner() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();

  // Form state
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [baseModel, setBaseModel] = useState('nano-banana-pro');
  const [loraSelections, setLoraSelections] = useState<Array<{ id: number; scale: number }>>([]);
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [steps, setSteps] = useState(28);
  const [guidance, setGuidance] = useState(0);
  const [seed, setSeed] = useState<string>('');
  const [numImages, setNumImages] = useState(1);
  const [resolution, setResolution] = useState('1K');
  const [aspectRatio, setAspectRatio] = useState('1:1');
  const [safetyTolerance, setSafetyTolerance] = useState('4');
  const [enableWebSearch, setEnableWebSearch] = useState(false);
  const [imageSizePreset, setImageSizePreset] = useState('landscape_4_3');
  const [autoExpand, setAutoExpand] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);

  // Current model capabilities
  const modelCaps = BASE_MODELS.find((m) => m.value === baseModel) || BASE_MODELS[0];

  // Multi-LoRA helpers
  const addLora = () => {
    if (loraSelections.length >= 2) return;
    // Pick the first available LoRA not already selected
    const usedIds = new Set(loraSelections.map((s) => s.id));
    const firstAvailable = loraList?.items.find((l) => !usedIds.has(l.id));
    if (firstAvailable) {
      setLoraSelections([...loraSelections, { id: firstAvailable.id, scale: 1.0 }]);
    }
  };
  const removeLora = (index: number) => {
    setLoraSelections(loraSelections.filter((_, i) => i !== index));
  };
  const updateLoraId = (index: number, id: number) => {
    const updated = [...loraSelections];
    updated[index] = { ...updated[index], id };
    setLoraSelections(updated);
  };
  const updateLoraScale = (index: number, scale: number) => {
    const updated = [...loraSelections];
    updated[index] = { ...updated[index], scale };
    setLoraSelections(updated);
  };
  const getAvailableLorasForSlot = (slotIndex: number) => {
    const usedIds = new Set(loraSelections.filter((_, i) => i !== slotIndex).map((s) => s.id));
    return (loraList?.items || []).filter((l) => !usedIds.has(l.id));
  };

  // Full-size modal — store only the ID so the modal always uses fresh polled data
  const [selectedImageId, setSelectedImageId] = useState<number | null>(null);

  // Fetch base model from settings to initialize
  const hasInitialized = useRef(false);
  const hasAppliedUrlParams = useRef(false);
  const { data: baseModelData } = useQuery({
    queryKey: ['base-model'],
    queryFn: settingsApi.getBaseModel,
  });

  useEffect(() => {
    if (baseModelData && !hasInitialized.current) {
      hasInitialized.current = true;
      const modelEntry = BASE_MODELS.find((m) => m.value === baseModelData.base_model);
      if (modelEntry) {
        setBaseModel(modelEntry.value);
        setGuidance(modelEntry.defaultGuidance);
      }
    }
  }, [baseModelData]);

  // Read URL params (?lora=ID&prompt=TEXT)
  useEffect(() => {
    if (hasAppliedUrlParams.current) return;
    const loraParam = searchParams.get('lora');
    const promptParam = searchParams.get('prompt');

    if (loraParam) {
      const parsed = parseInt(loraParam, 10);
      if (!isNaN(parsed)) {
        hasAppliedUrlParams.current = true;
        setLoraSelections([{ id: parsed, scale: 1.0 }]);
        // Fetch the LoRA to sync baseModel
        generationApi.getLora(parsed).then((lora) => {
          const modelEntry = BASE_MODELS.find((m) => m.value === lora.base_model);
          if (modelEntry) {
            setBaseModel(modelEntry.value);
            setGuidance(modelEntry.defaultGuidance);
          }
        }).catch(() => {
          // LoRA not found or not accessible — ignore
        });
      }
    }
    if (promptParam) {
      hasAppliedUrlParams.current = true;
      setPrompt(decodeURIComponent(promptParam));
    }
  }, [searchParams]);

  // Fetch completed + uploaded LoRA models filtered by base model
  const { data: loraList } = useQuery({
    queryKey: ['lora-models', 'completed,uploaded', baseModel],
    queryFn: () => generationApi.listLora({ status: 'completed,uploaded', base_model: baseModel }),
  });

  // Fetch generated images with polling
  const { data: generatedImages, isLoading: imagesLoading } = useQuery({
    queryKey: ['generated-images'],
    queryFn: () => generationApi.listImages({ limit: 100 }),
    refetchInterval: 3000,
  });

  // Fetch generation costs for cost estimate display
  const { data: generationCosts } = useQuery({
    queryKey: ['generation-costs'],
    queryFn: () => billingApi.getGenerationCosts(),
    staleTime: 5 * 60 * 1000, // costs don't change often
  });

  // Check if this model has variable pricing (resolution multipliers, megapixel, etc.)
  const hasVariablePricing = generationCosts?.variable_pricing_models?.includes(baseModel) ?? false;

  // Dynamic cost query — only fires for models with variable pricing
  const { data: dynamicEstimate } = useQuery({
    queryKey: ['generation-estimate', baseModel, resolution, enableWebSearch, width, height, imageSizePreset, loraSelections.length > 0],
    queryFn: () => billingApi.estimateGenerationCost({
      base_model: baseModel,
      resolution: modelCaps.usesResolutionAspect ? resolution : undefined,
      enable_web_search: modelCaps.hasWebSearch ? enableWebSearch : undefined,
      width: (modelCaps.hasWidthHeight || (modelCaps.hasImageSizePreset && imageSizePreset === 'custom')) ? width : undefined,
      height: (modelCaps.hasWidthHeight || (modelCaps.hasImageSizePreset && imageSizePreset === 'custom')) ? height : undefined,
      image_size: (modelCaps.hasImageSizePreset && imageSizePreset !== 'custom') ? imageSizePreset : undefined,
      with_lora: modelCaps.hasLora && loraSelections.length > 0,
    }),
    enabled: hasVariablePricing,
    staleTime: 60_000,
  });

  // Compute estimated cost in sparks
  const estimatedCostPerImage = (() => {
    // Use dynamic estimate for models with variable pricing
    if (hasVariablePricing && dynamicEstimate?.estimated_sparks != null) {
      return dynamicEstimate.estimated_sparks;
    }
    // Fall back to static costs
    if (!generationCosts?.costs) return null;
    const modelCosts = generationCosts.costs[baseModel];
    if (!modelCosts) return null;
    const hasLora = modelCaps.hasLora && loraSelections.length > 0;
    return hasLora ? (modelCosts.with_lora ?? null) : (modelCosts.without_lora ?? null);
  })();
  const totalEstimatedCost = estimatedCostPerImage != null ? estimatedCostPerImage * numImages : null;

  // Generate mutation
  const deleteMutation = useMutation({
    mutationFn: generationApi.deleteImage,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['generated-images'] });
    },
    onError: (err: Error) => {
      toast.error(`Delete failed: ${err.message}`);
    },
  });

  const expandMutation = useMutation({
    mutationFn: (promptText: string) => generationApi.expandPrompt(promptText),
    onSuccess: (data) => {
      setPrompt(data.expanded_prompt);
      toast.success('Prompt expanded');
    },
    onError: (err: Error) => {
      toast.error(`Expand failed: ${err.message}`);
    },
  });

  const generateMutation = useMutation({
    mutationFn: generationApi.generate,
    onSuccess: (data) => {
      if (loraSelections.length > 0) {
        trackFunnelStep('training', 'first_generation', {
          loraIds: loraSelections.map((s) => s.id),
          baseModel,
          numImages: data.generated_image_ids.length,
        });
      }
      toast.success(`Generation started (${data.generated_image_ids.length} images)`);
      queryClient.invalidateQueries({ queryKey: ['generated-images'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: (err: Error) => {
      toast.error(`Generation failed: ${err.message}`);
    },
  });

  const buildGenerateParams = (finalPrompt: string) => {
    const params: Parameters<typeof generationApi.generate>[0] = {
      prompt: finalPrompt,
      base_model: baseModel,
      num_images: numImages,
    };

    if (modelCaps.hasNegativePrompt && negativePrompt.trim()) params.negative_prompt = negativePrompt.trim();
    if (seed) params.seed = parseInt(seed);

    if (modelCaps.hasLora && loraSelections.length > 0) {
      params.loras = loraSelections.map((s) => ({ lora_model_id: s.id, lora_scale: s.scale }));
    }

    if (modelCaps.hasWidthHeight) {
      params.width = width;
      params.height = height;
    }
    if (modelCaps.hasStepsGuidance) {
      params.num_inference_steps = steps;
      params.guidance_scale = guidance;
    }
    if (modelCaps.usesResolutionAspect) {
      params.resolution = resolution;
      params.aspect_ratio = aspectRatio;
    }
    if (modelCaps.hasImageSizePreset) {
      if (imageSizePreset === 'custom') {
        params.width = width;
        params.height = height;
      } else {
        params.image_size = imageSizePreset;
      }
    }
    if (modelCaps.hasSafetyTolerance) {
      params.safety_tolerance = safetyTolerance;
    }
    if (modelCaps.hasWebSearch) {
      params.enable_web_search = enableWebSearch;
    }

    return params;
  };

  const handleGenerate = async () => {
    if (!prompt.trim()) {
      toast.error('Please enter a prompt');
      return;
    }

    let finalPrompt = prompt.trim();
    setIsGenerating(true);

    if (autoExpand) {
      try {
        const result = await generationApi.expandPrompt(finalPrompt);
        finalPrompt = result.expanded_prompt;
        setPrompt(finalPrompt);
      } catch (err) {
        toast.error(`Auto-expand failed: ${err instanceof Error ? err.message : String(err)}`);
        setIsGenerating(false);
        return;
      }
    }

    generateMutation.mutate(buildGenerateParams(finalPrompt), {
      onSettled: () => setIsGenerating(false),
    });
  };

  const handleSizePreset = (w: number, h: number) => {
    setWidth(w);
    setHeight(h);
  };

  const images = generatedImages?.items || [];
  const selectedImage = selectedImageId != null
    ? images.find((img) => img.id === selectedImageId) ?? null
    : null;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Generate</h1>
        <p className="text-muted-foreground mt-1">
          Create images with your trained LoRAs
        </p>
      </div>

      {/* Generation Form */}
      <section className="bg-card rounded-xl border border-border p-6 space-y-4">
        {/* Prompt */}
        <div>
          <label className="block text-sm font-medium mb-1">Prompt</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe the image you want to generate..."
            className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                handleGenerate();
              }
            }}
          />
          <div className="flex items-center justify-between mt-1">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={autoExpand}
                onChange={(e) => setAutoExpand(e.target.checked)}
                className="rounded"
              />
              Auto-expand on generate
              {generationCosts?.expand_prompt_cost != null && (
                <span className="inline-flex items-center gap-0.5 text-amber-600 dark:text-amber-400">
                  <Zap className="h-3 w-3" />~{generationCosts.expand_prompt_cost < 1 ? '<1' : Math.round(generationCosts.expand_prompt_cost)}
                </span>
              )}
            </label>
            <div className="flex items-center gap-2">
              {generationCosts?.expand_prompt_cost != null && (
                <span className="text-xs text-muted-foreground inline-flex items-center gap-0.5">
                  <Zap className="h-3 w-3 text-amber-600 dark:text-amber-400" />~{generationCosts.expand_prompt_cost < 1 ? '<1' : Math.round(generationCosts.expand_prompt_cost)}
                </span>
              )}
              <button
                onClick={() => expandMutation.mutate(prompt.trim())}
                disabled={expandMutation.isPending || !prompt.trim()}
                className="flex items-center gap-1.5 px-3 py-1 text-xs text-muted-foreground hover:text-foreground border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
              >
                {expandMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Wand2 className="h-3.5 w-3.5" />
                )}
                Expand
              </button>
            </div>
          </div>
        </div>

        {/* Model selector + LoRA + quick params */}
        <div className="flex flex-wrap gap-4 items-end">
          {/* Base Model */}
          <ModelSelector
            label="Model"
            models={BASE_MODELS}
            value={baseModel}
            onChange={(v) => {
              const caps = BASE_MODELS.find((m) => m.value === v);
              setBaseModel(v);
              setLoraSelections([]);
              setGuidance(caps?.defaultGuidance ?? 0);
              if (numImages > (caps?.maxImages ?? 8)) setNumImages(caps?.maxImages ?? 8);
              // Reset safety tolerance to model default
              const defaultSafety = DEFAULT_SAFETY_TOLERANCE[v];
              if (defaultSafety) setSafetyTolerance(defaultSafety);
            }}
            size="sm"
          />

          {/* LoRA selections (max 2) — only for models that support LoRA */}
          {modelCaps.hasLora && (
            <div className="flex flex-wrap gap-3 items-end">
              {loraSelections.map((sel, idx) => {
                const available = getAvailableLorasForSlot(idx);
                return (
                  <div key={idx} className="flex items-end gap-2">
                    <div className="min-w-[180px]">
                      <label className="block text-xs text-muted-foreground mb-1">
                        LoRA {loraSelections.length > 1 ? idx + 1 : ''}
                      </label>
                      <select
                        value={sel.id}
                        onChange={(e) => updateLoraId(idx, parseInt(e.target.value))}
                        className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                      >
                        {available.map((lora) => (
                          <option key={lora.id} value={lora.id}>
                            {lora.trigger_word ? `${lora.name} (${lora.trigger_word})` : lora.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="w-28">
                      <label className="block text-xs text-muted-foreground mb-1">
                        Scale: {sel.scale.toFixed(1)}
                      </label>
                      <Slider
                        min={0}
                        max={20}
                        value={Math.round(sel.scale * 10)}
                        onChange={(v) => updateLoraScale(idx, v / 10)}
                        className="w-full"
                      />
                    </div>
                    <button
                      onClick={() => removeLora(idx)}
                      className="p-2 text-muted-foreground hover:text-red-500 transition-colors"
                      title="Remove LoRA"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                );
              })}
              {loraSelections.length < 2 && (loraList?.items.length ?? 0) > loraSelections.length && (
                <button
                  onClick={addLora}
                  className="flex items-center gap-1 px-3 py-2 text-sm border border-dashed border-border rounded-lg text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
                >
                  <Plus className="h-3.5 w-3.5" />
                  {loraSelections.length === 0 ? 'Add LoRA' : 'Add 2nd LoRA'}
                </button>
              )}
            </div>
          )}

          {/* Num images */}
          <div className="w-24">
            <label className="block text-xs text-muted-foreground mb-1">Images</label>
            <select
              value={numImages}
              onChange={(e) => setNumImages(parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm"
            >
              {[1, 2, 4, 8].filter((n) => n <= modelCaps.maxImages).map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>

          {/* Generate button + cost estimate */}
          <div className="flex items-end gap-3">
            <button
              onClick={handleGenerate}
              disabled={isGenerating || !prompt.trim()}
              className="flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 font-medium"
            >
              {isGenerating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              Generate
            </button>
            {totalEstimatedCost != null && (
              <span className="inline-flex items-center gap-1 text-sm text-amber-600 dark:text-amber-400 font-medium pb-2">
                <Zap className="h-3.5 w-3.5" />
                {totalEstimatedCost}{numImages > 1 && <span className="text-xs text-muted-foreground font-normal">({estimatedCostPerImage} x {numImages})</span>}
              </span>
            )}
          </div>
        </div>

        {/* Advanced toggle */}
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          Advanced Parameters
        </button>

        {/* Advanced params */}
        {showAdvanced && (
          <div className="border border-border rounded-lg p-4 space-y-4">
            {/* Negative prompt (only for models that support it) */}
            {modelCaps.hasNegativePrompt && (
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Negative Prompt</label>
                <input
                  type="text"
                  value={negativePrompt}
                  onChange={(e) => setNegativePrompt(e.target.value)}
                  placeholder="Things to avoid..."
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                />
              </div>
            )}

            {/* Image size presets + custom (flux-2-pro) */}
            {modelCaps.hasImageSizePreset && (
              <div className="space-y-2">
                <label className="block text-xs text-muted-foreground mb-1">Image Size</label>
                <div className="flex flex-wrap gap-2">
                  {IMAGE_SIZE_PRESETS.map((preset) => (
                    <button
                      key={preset.value}
                      onClick={() => setImageSizePreset(preset.value)}
                      className={cn(
                        'flex items-center gap-1.5 px-3 py-1.5 text-xs border rounded-lg transition-colors',
                        imageSizePreset === preset.value
                          ? 'border-primary bg-primary/5 text-primary'
                          : 'border-border hover:bg-muted'
                      )}
                    >
                      {preset.value !== 'custom' && <AspectIcon ratio={preset.ratio} />}
                      {preset.label}
                    </button>
                  ))}
                </div>
                {imageSizePreset === 'custom' && (
                  <div className="flex items-center gap-2">
                    <div className="w-28">
                      <label className="block text-xs text-muted-foreground mb-1">Width</label>
                      <input
                        type="number"
                        value={width}
                        onChange={(e) => setWidth(Math.max(256, Math.min(2048, parseInt(e.target.value) || 256)))}
                        min={256}
                        max={2048}
                        step={8}
                        className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                      />
                    </div>
                    <span className="text-muted-foreground mt-5">&times;</span>
                    <div className="w-28">
                      <label className="block text-xs text-muted-foreground mb-1">Height</label>
                      <input
                        type="number"
                        value={height}
                        onChange={(e) => setHeight(Math.max(256, Math.min(2048, parseInt(e.target.value) || 256)))}
                        min={256}
                        max={2048}
                        step={8}
                        className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                      />
                    </div>
                    <span className="text-xs text-muted-foreground mt-5">{width} &times; {height} px</span>
                  </div>
                )}
              </div>
            )}

            {/* Size presets (width/height models) */}
            {modelCaps.hasWidthHeight && (
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Size</label>
                <div className="flex flex-wrap gap-2">
                  {SIZE_PRESETS.map((preset) => (
                    <button
                      key={preset.label}
                      onClick={() => handleSizePreset(preset.w, preset.h)}
                      className={cn(
                        'px-3 py-1.5 text-xs border rounded-lg transition-colors',
                        width === preset.w && height === preset.h
                          ? 'border-primary bg-primary/5 text-primary'
                          : 'border-border hover:bg-muted'
                      )}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Resolution + Aspect Ratio (resolution/aspect models) */}
            {modelCaps.usesResolutionAspect && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Resolution</label>
                  <div className="flex gap-2">
                    {RESOLUTIONS.map((r) => (
                      <button
                        key={r.value}
                        onClick={() => setResolution(r.value)}
                        className={cn(
                          'px-4 py-1.5 text-xs border rounded-lg transition-colors',
                          resolution === r.value
                            ? 'border-primary bg-primary/5 text-primary'
                            : 'border-border hover:bg-muted'
                        )}
                      >
                        {r.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Aspect Ratio</label>
                  <select
                    value={aspectRatio}
                    onChange={(e) => setAspectRatio(e.target.value)}
                    className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                  >
                    {ASPECT_RATIOS.map((ar) => (
                      <option key={ar.value} value={ar.value}>{ar.label}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            {/* Safety Tolerance + Web Search */}
            {(modelCaps.hasSafetyTolerance || modelCaps.hasWebSearch) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {modelCaps.hasSafetyTolerance && (
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Safety Tolerance</label>
                    <select
                      value={safetyTolerance}
                      onChange={(e) => setSafetyTolerance(e.target.value)}
                      className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                    >
                      {SAFETY_LEVELS.filter((s) => s.level <= (modelCaps.maxSafetyLevel ?? 6)).map((s) => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                )}
                {modelCaps.hasWebSearch && (
                  <div className="flex items-end pb-1">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={enableWebSearch}
                        onChange={(e) => setEnableWebSearch(e.target.checked)}
                        className="rounded"
                      />
                      Enable web search
                    </label>
                  </div>
                )}
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Steps */}
              {modelCaps.hasStepsGuidance && (
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">
                    Steps: {steps}
                  </label>
                  <Slider
                    min={1}
                    max={50}
                    value={steps}
                    onChange={(v) => setSteps(v)}
                    className="w-full"
                  />
                </div>
              )}

              {/* Guidance */}
              {modelCaps.hasStepsGuidance && (
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">
                    Guidance: {guidance.toFixed(1)}
                  </label>
                  <Slider
                    min={0}
                    max={200}
                    value={Math.round(guidance * 10)}
                    onChange={(v) => setGuidance(v / 10)}
                    className="w-full"
                  />
                </div>
              )}

              {/* Seed */}
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Seed</label>
                <input
                  type="text"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value.replace(/\D/g, ''))}
                  placeholder="Random"
                  className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                />
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Generated Images Grid */}
      <section>
        <h2 className="font-semibold mb-3">
          Generated Images
          {generatedImages && <span className="text-muted-foreground font-normal ml-2">({generatedImages.total})</span>}
        </h2>
        {imagesLoading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : images.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground">
            <Sparkles className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p>No images generated yet</p>
            <p className="text-sm mt-1">Enter a prompt above and click Generate</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {images.map((img) => (
              <GeneratedImageCard
                key={img.id}
                image={img}
                onClick={() => setSelectedImageId(img.id)}
                onDelete={(id) => deleteMutation.mutate(id)}
              />
            ))}
          </div>
        )}
      </section>

      {/* Full-size modal */}
      {selectedImage && (
        <>
          <div
            className="fixed inset-0 bg-black/70 z-50"
            onClick={() => setSelectedImageId(null)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-card rounded-xl shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between p-4 border-b border-border">
                <h3 className="font-semibold">Generated Image #{selectedImage.id}</h3>
                <button
                  onClick={() => setSelectedImageId(null)}
                  className="p-1 hover:bg-muted rounded-lg transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-4 space-y-4">
                {selectedImage.status === 'completed' && selectedImage.object_key ? (
                  <img
                    src={generationApi.getImageUrl(selectedImage.id)}
                    alt={selectedImage.prompt}
                    className="max-w-full mx-auto rounded-lg"
                  />
                ) : (
                  <div className="flex items-center justify-center h-64 bg-muted/30 rounded-lg">
                    {selectedImage.status === 'failed' ? (
                      <p className="text-red-600 text-sm">{selectedImage.error_message || 'Generation failed'}</p>
                    ) : (
                      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                    )}
                  </div>
                )}
                <div className="space-y-2 text-sm">
                  <div>
                    <span className="font-medium">Prompt:</span>
                    <p className="text-muted-foreground mt-0.5">{selectedImage.prompt}</p>
                  </div>
                  {selectedImage.negative_prompt && (
                    <div>
                      <span className="font-medium">Negative:</span>
                      <p className="text-muted-foreground mt-0.5">{selectedImage.negative_prompt}</p>
                    </div>
                  )}
                  <div className="flex flex-wrap gap-4">
                    <span><span className="font-medium">Model:</span> {selectedImage.base_model}</span>
                    {selectedImage.width && selectedImage.height && (
                      <span><span className="font-medium">Size:</span> {selectedImage.width}x{selectedImage.height}</span>
                    )}
                    {selectedImage.loras && selectedImage.loras.length > 0 ? (
                      <span>
                        <span className="font-medium">LoRA{selectedImage.loras.length > 1 ? 's' : ''}:</span>{' '}
                        {selectedImage.loras.map((l, i) => (
                          <span key={l.lora_model_id}>
                            {i > 0 && ', '}
                            <Link href="/models" className="text-primary hover:underline" onClick={() => setSelectedImageId(null)}>
                              {l.lora_model_name}
                            </Link>
                            {selectedImage.loras.length > 1 && (
                              <span className="text-muted-foreground text-xs ml-0.5">({l.lora_scale.toFixed(1)})</span>
                            )}
                          </span>
                        ))}
                      </span>
                    ) : selectedImage.lora_model_name && selectedImage.lora_model_id ? (
                      <span>
                        <span className="font-medium">LoRA:</span>{' '}
                        <Link href="/models" className="text-primary hover:underline" onClick={() => setSelectedImageId(null)}>
                          {selectedImage.lora_model_name}
                        </Link>
                      </span>
                    ) : null}
                    {selectedImage.generation_params && (() => {
                      const gp = selectedImage.generation_params as Record<string, unknown>;
                      return (
                        <>
                          {gp.num_inference_steps != null && (
                            <span><span className="font-medium">Steps:</span> {gp.num_inference_steps as number}</span>
                          )}
                          {gp.guidance_scale != null && (
                            <span><span className="font-medium">Guidance:</span> {gp.guidance_scale as number}</span>
                          )}
                          {gp.resolution != null && (
                            <span><span className="font-medium">Resolution:</span> {String(gp.resolution)}</span>
                          )}
                          {gp.aspect_ratio != null && (
                            <span><span className="font-medium">Aspect Ratio:</span> {String(gp.aspect_ratio)}</span>
                          )}
                          {gp.image_size != null && (
                            <span><span className="font-medium">Image Size:</span> {String(gp.image_size)}</span>
                          )}
                          {gp.safety_tolerance != null && (
                            <span><span className="font-medium">Safety:</span> {String(gp.safety_tolerance)}</span>
                          )}
                          {gp.enable_web_search != null && (
                            <span><span className="font-medium">Web Search:</span> {gp.enable_web_search ? 'On' : 'Off'}</span>
                          )}
                          {gp.actual_seed != null && (
                            <span><span className="font-medium">Seed:</span> {gp.actual_seed as number}</span>
                          )}
                        </>
                      );
                    })()}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
