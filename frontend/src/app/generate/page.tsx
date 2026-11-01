'use client';

import LibraryImage from '@/components/LibraryImage';

import { useState, useEffect, useRef, useMemo, Suspense } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { generationApi, settingsApi, billingApi, imagesApi } from '@/lib/api';
import { Loader2, X, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { trackFunnelStep } from '@/lib/observability';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import Stage from '@/components/tools/Stage';
import SheetButton from '@/components/tools/SheetButton';
import Composer from '@/components/tools/Composer';
import Notice from '@/components/tools/Notice';
import type { GeneratedImage } from '@/types';
import { useModelCatalog } from '@/hooks/useModelCatalog';
import { Slider } from '@/components/Slider';

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
  const dirty = useRef(new Set<string>());
  const [references, setReferences] = useState<Array<{ id: number; url: string }>>([]);

  useEffect(() => {
    const ids = (searchParams.get('sources') || '').split(',').map(Number).filter(id => Number.isInteger(id) && id > 0);
    let active = true;
    Promise.all(ids.map(async id => {
      try {
        const image = await imagesApi.get(id);
        const thumbnail = image.thumbnail_uri_medium || image.thumbnail_uri_small;
        return { id, url: thumbnail ? imagesApi.getThumbnailUrl(thumbnail.split('/').pop()!) : imagesApi.getImageUrl(image.object_key.split('/').pop()!) };
      } catch {
        toast.error(`Could not load selected image ${id}`);
        return null;
      }
    })).then(items => {
      if (active) setReferences(items.filter((item): item is NonNullable<typeof item> => item !== null));
    });
    return () => { active = false; };
  }, [searchParams]);

  // Form state
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState('');
  const [notice, setNotice] = useState('');
  const [baseModel, setBaseModel] = useState('');
  const [quality, setQuality] = useState('');
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

  const { data: catalog } = useModelCatalog();
  const BASE_MODELS = useMemo(() => (catalog?.generation ?? []).map(m => ({ value: m.key, label: m.label, defaultGuidance: m.params.steps_guidance?.guidance?.default ?? 0, hasLora: m.supports_lora, hasStepsGuidance: !!m.params.steps_guidance, hasWidthHeight: false, usesResolutionAspect: !!(m.params.resolution || m.params.aspect_ratio), hasSafetyTolerance: !!m.params.safety_tolerance, hasWebSearch: !!m.params.enable_web_search, hasImageSizePreset: !!m.params.image_size, hasNegativePrompt: !!m.params.negative_prompt, maxSafetyLevel: 6, maxImages: m.max_num_images || 1 })), [catalog]);
  const modelCaps = BASE_MODELS.find(m => m.value === baseModel) ?? { hasLora: false, hasStepsGuidance: false, hasWidthHeight: false, usesResolutionAspect: false, hasSafetyTolerance: false, hasWebSearch: false, hasImageSizePreset: false, hasNegativePrompt: false, maxSafetyLevel: 6, maxImages: 1 };
  const model = catalog?.generation.find(m => m.key === baseModel);
  const spec = model?.params ?? {};
  const RESOLUTIONS = (spec.resolution?.options ?? []).map(value => ({ value, label: value }));
  const ASPECT_RATIOS = (spec.aspect_ratio?.options ?? []).map(value => ({ value, label: value }));
  const SAFETY_LEVELS = (spec.safety_tolerance?.options ?? []).map(value => ({ value, label: value, level: Number(value) }));
  const IMAGE_SIZE_PRESETS = [...(spec.image_size?.options ?? []), ...(spec.image_size?.custom_size ? ['custom'] : [])].map(value => ({ value, label: value.replaceAll('_', ' '), ratio: '1:1' }));
  // Model changes preserve supported values and report any adjustments below.

  const initializedModel = useRef('');
  useEffect(() => {
    if (!model || initializedModel.current === model.key) return;
    initializedModel.current = model.key;
    setResolution(model.params.resolution?.default ?? '');
    setAspectRatio(model.params.aspect_ratio?.default ?? '');
    setImageSizePreset(model.params.image_size?.default ?? '');
    setQuality(model.params.quality?.default ?? '');
    setSafetyTolerance(model.params.safety_tolerance?.default ?? '');
    setSteps(model.params.steps_guidance?.steps?.default ?? 28);
    setGuidance(model.params.steps_guidance?.guidance?.default ?? 0);
  }, [model]);

  const { data: generationConfig } = useQuery({
    queryKey: ['generation-config', baseModel],
    queryFn: () => settingsApi.getGenerationConfig(baseModel),
    enabled: !!model,
  });
  const configuredModel = useRef('');
  useEffect(() => {
    if (!generationConfig || !model || configuredModel.current) return;
    configuredModel.current = model.key;
    if (model.params.image_size?.custom_size) {
      setWidth(generationConfig.width);
      setHeight(generationConfig.height);
    }
    const bounds = model.params.steps_guidance;
    if (bounds?.steps && bounds.guidance) {
      setSteps(Math.max(bounds.steps.minimum, Math.min(bounds.steps.maximum, generationConfig.num_inference_steps)));
      setGuidance(Math.max(bounds.guidance.minimum, Math.min(bounds.guidance.maximum, generationConfig.guidance_scale)));
    }
  }, [generationConfig, model]);

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
  useEffect(() => {
    const id = Number(searchParams.get('image'));
    if (Number.isInteger(id) && id > 0) setSelectedImageId(id);
  }, [searchParams]);
  const { data: linkedImage } = useQuery({
    queryKey: ['generated-image', selectedImageId],
    queryFn: () => generationApi.getImage(selectedImageId!),
    enabled: selectedImageId != null,
    refetchInterval: 5000,
  });

  // Fetch base model from settings to initialize
  const hasInitialized = useRef(false);
  const hasAppliedUrlParams = useRef(false);
  const { data: baseModelData } = useQuery({
    queryKey: ['base-model'],
    queryFn: settingsApi.getBaseModel,
  });

  useEffect(() => {
    if (catalog && baseModelData && !hasInitialized.current) {
      hasInitialized.current = true;
      const modelEntry = BASE_MODELS.find((m) => m.value === baseModelData.base_model) ?? BASE_MODELS.find(m => m.value === catalog.defaults.generation_model);
      if (modelEntry) {
        setBaseModel(modelEntry.value);
        setGuidance(modelEntry.defaultGuidance);
      }
    }
  }, [baseModelData, catalog, BASE_MODELS]);

  // Read URL params (?lora=ID&prompt=TEXT)
  useEffect(() => {
    if (!catalog || hasAppliedUrlParams.current) return;
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
            hasInitialized.current = true;
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
      setPrompt(promptParam);
    }
  }, [searchParams, catalog, BASE_MODELS]);

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
    queryKey: ['generation-estimate', baseModel, resolution, enableWebSearch, width, height, imageSizePreset, quality, loraSelections.length > 0],
    queryFn: () => billingApi.estimateGenerationCost({
      base_model: baseModel,
      resolution: modelCaps.usesResolutionAspect ? resolution : undefined,
      enable_web_search: modelCaps.hasWebSearch ? enableWebSearch : undefined,
      width: (modelCaps.hasWidthHeight || (modelCaps.hasImageSizePreset && imageSizePreset === 'custom')) ? width : undefined,
      height: (modelCaps.hasWidthHeight || (modelCaps.hasImageSizePreset && imageSizePreset === 'custom')) ? height : undefined,
      image_size: (modelCaps.hasImageSizePreset && imageSizePreset !== 'custom') ? imageSizePreset : undefined,
      quality: spec.quality ? quality : undefined,
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
    if (spec.seed && seed) params.seed = parseInt(seed);
    if (spec.quality && quality) params.quality = quality;

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
      if (spec.resolution && resolution) params.resolution = resolution;
      if (spec.aspect_ratio && aspectRatio) params.aspect_ratio = aspectRatio;
    }
    if (modelCaps.hasImageSizePreset) {
      if (imageSizePreset === 'custom') {
        params.width = width;
        params.height = height;
      } else if (imageSizePreset) {
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
    if (!model) { toast.error('Model catalog is not ready'); return; }
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

  function changeModel(key: string) {
    if (key === baseModel) return;
    const next = catalog?.generation.find(entry => entry.key === key);
    if (!next) return;
    const changes: string[] = [];
    const options = [
      ['Resolution', resolution, setResolution, next.params.resolution],
      ['Shape', aspectRatio, setAspectRatio, next.params.aspect_ratio],
      ['Image size', imageSizePreset, setImageSizePreset, next.params.image_size],
      ['Quality', quality, setQuality, next.params.quality],
      ['Safety tolerance', safetyTolerance, setSafetyTolerance, next.params.safety_tolerance],
    ] as const;
    for (const [label, value, setter, param] of options) {
      const supported = param?.options?.includes(value) || (value === 'custom' && param?.custom_size);
      const replacement = supported ? value : param?.default ?? '';
      if (value !== replacement && value && dirty.current.has(label)) changes.push(`${label} ${replacement ? `changed to ${replacement}` : 'removed'}`);
      if (replacement !== value) dirty.current.delete(label);
      setter(replacement);
    }
    if (loraSelections.length) {
      setLoraSelections([]);
      changes.push('LoRAs removed because they belong to the previous model');
    }
    if (!next.params.negative_prompt && negativePrompt) {
      setNegativePrompt('');
      changes.push('Negative prompt removed');
    }
    if (!next.params.seed && seed) {
      setSeed('');
      changes.push('Seed removed');
    }
    if (!next.params.enable_web_search && enableWebSearch) {
      setEnableWebSearch(false);
      changes.push('Web search disabled');
    }
    const bounds = next.params.steps_guidance;
    for (const [label, value, setter, bound] of [
      ['Steps', steps, setSteps, bounds?.steps],
      ['Guidance', guidance, setGuidance, bounds?.guidance],
    ] as const) {
      const replacement = bound ? (spec.steps_guidance ? Math.max(bound.minimum, Math.min(bound.maximum, value)) : bound.default) : 0;
      if (dirty.current.has(label) && replacement !== value) changes.push(`${label} ${bound ? `changed to ${replacement}` : 'removed'}`);
      if (replacement !== value) dirty.current.delete(label);
      setter(replacement);
    }
    if (numImages > next.max_num_images) {
      setNumImages(next.max_num_images);
      changes.push(`Results changed to ${next.max_num_images}`);
    }
    setNotice(changes.join('. '));
    initializedModel.current = key;
    setBaseModel(key);
  }

  const images = generatedImages?.items || [];
  const selectedImage = selectedImageId != null
    ? images.find((img) => img.id === selectedImageId) ?? linkedImage ?? null
    : null;

  const runs = new Map<string, GeneratedImage[]>();
  for (const image of images) {
    const key = image.job_id != null ? `job-${image.job_id}` : `image-${image.id}`;
    runs.set(key, [...(runs.get(key) ?? []), image]);
  }
  const chipClass = 'min-w-0 max-w-full rounded-md border border-input bg-background px-2 py-1 text-xs';
  const modelControl = (
    <select aria-label="Model" value={baseModel} onChange={event => changeModel(event.target.value)} className={chipClass}>
      {BASE_MODELS.map(entry => (
        <option key={entry.value} value={entry.value}>{entry.label}</option>
      ))}
    </select>
  );
  const shapeControl = (spec.aspect_ratio ? (
    <select aria-label="Shape" value={aspectRatio} onChange={event => { dirty.current.add('Shape'); setAspectRatio(event.target.value); }} className={chipClass}>
      {ASPECT_RATIOS.map(option => (
        <option key={option.value}>{option.value}</option>
      ))}
    </select>
  ) : spec.image_size ? (
    <select aria-label="Shape" value={imageSizePreset} onChange={event => { dirty.current.add('Image size'); setImageSizePreset(event.target.value); }} className={chipClass}>
      {IMAGE_SIZE_PRESETS.map(option => (
        <option key={option.value} value={option.value}>{option.label}</option>
      ))}
    </select>
  ) : <span className={chipClass}>{width} × {height}</span>);
  const countControl = (
    <select aria-label="Results" value={numImages} onChange={event => setNumImages(Number(event.target.value))} className={chipClass}>
      {Array.from({ length: modelCaps.maxImages }, (_, index) => index + 1).map(count => (
        <option key={count} value={count}>{count} {count === 1 ? 'result' : 'results'}</option>
      ))}
    </select>
  );
  const qualityControl = spec.quality ? (
    <select aria-label="Quality" value={quality} onChange={event => { dirty.current.add('Quality'); setQuality(event.target.value); }} className={chipClass}>
      {spec.quality.options?.map(value => <option key={value}>{value}</option>)}
    </select>
  ) : spec.resolution ? (
    <select aria-label="Resolution" value={resolution} onChange={event => { dirty.current.add('Resolution'); setResolution(event.target.value); }} className={chipClass}>
      {RESOLUTIONS.map(option => (
        <option key={option.value}>{option.value}</option>
      ))}
    </select>
  ) : null;

  return (
    <div className="-mx-5 -my-5 h-[calc(100%+40px)] min-h-0">
      <style jsx global>{`
        @keyframes create-shimmer {
          to { background-position: -220% 0; }
        }
      `}</style>
      <Stage
        mobileFeedKey={images.length}
        mobileSheets={{ Model: <label className="grid gap-2">Model{modelControl}</label> }}
        canvas={
          <>
            {references.length > 0 && (
              <div className="shrink-0 space-y-2">
                <p className="text-xs text-muted-foreground">Selected images for visual reference while writing. Create uses your prompt and optional LoRAs.</p>
                <div className="flex gap-2 overflow-x-auto">
                  {references.map(image => (
                    <LibraryImage key={image.id} src={image.url} alt={`Selected image ${image.id}`} className="h-[52px] w-[52px] shrink-0 rounded object-cover" />
                  ))}
                </div>
              </div>
            )}
            {imagesLoading && <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />}
            {Array.from(runs, ([key, run], index) => {
              const first = run[0];
              const params = first.generation_params;
              const shape = String(params?.aspect_ratio || params?.image_size || `${first.width ?? '?'} × ${first.height ?? '?'}`);
              const cost = run.reduce((sum, image) => sum + (image.cost_sparks ?? 0), 0);
              return (
                <section key={key} style={{ '--mobile-run-order': runs.size - index } as React.CSSProperties} className="create-run shrink-0 space-y-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2 text-[13px]">
                    <span className="min-w-0 flex-1 truncate font-medium" title={first.prompt}>{first.prompt}</span>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {catalog?.generation.find(entry => entry.key === first.base_model)?.label || first.base_model} · {shape} · {run.some(image => image.cost_sparks != null) ? `${cost} sparks` : 'Cost pending'}
                    </span>
                  </div>
                  <div className="flex h-[210px] gap-1.5 overflow-x-auto">
                    {run.map(image => (
                      <button
                        key={image.id}
                        aria-label={`Open result ${image.id}`}
                        onClick={() => setSelectedImageId(image.id)}
                        style={{ aspectRatio: `${image.width || 1024} / ${image.height || 1024}` }}
                        className="relative h-full shrink-0 overflow-hidden rounded-md bg-muted"
                      >
                        {image.status === 'completed' && image.object_key ? (
                          <LibraryImage src={generationApi.getImageUrl(image.id)} alt={image.prompt} className="h-full w-full object-contain" />
                        ) : image.status === 'failed' ? (
                          <span className="block max-w-64 p-3 text-sm text-destructive">{image.error_message || 'Generation failed'}</span>
                        ) : <span className="block h-full w-full bg-[linear-gradient(100deg,transparent_20%,hsl(var(--muted-foreground)/0.12)_45%,transparent_70%)] bg-[length:220%_100%] motion-safe:animate-[create-shimmer_1.4s_linear_infinite]" />}
                      </button>
                    ))}
                  </div>
                </section>
              );
            })}
          </>
        }
        composer={
          <Composer
            value={prompt}
            onChange={setPrompt}
            onApply={handleGenerate}
            disabled={!model || isGenerating || !prompt.trim()}
            count={numImages}
            cost={totalEstimatedCost ?? undefined}
            placeholder="Describe the image you want to create…"
            action="Create"
            mobileChips={<><SheetButton title="Model" label={model?.label || 'Model'} /><SheetButton title="Create settings" label={`${aspectRatio || imageSizePreset || 'Shape'} · ${numImages} ${numImages === 1 ? 'result' : 'results'}`} /></>}
            chips={<>{modelControl}{shapeControl}{countControl}{qualityControl}</>}
          />
        }
        settings={
          <>
            <h2 className="font-semibold">Create settings</h2>
            <Notice>{notice}</Notice>
            <label className="grid gap-1">Model{modelControl}</label>
            <label className="grid gap-1">Shape{shapeControl}</label>
            <label className="grid gap-1">Results{countControl}</label>
            {qualityControl && <label className="grid gap-1">{spec.quality ? 'Quality' : 'Resolution'}{qualityControl}</label>}
            <p className="font-mono text-xs text-muted-foreground">{totalEstimatedCost != null ? `about ${totalEstimatedCost} sparks` : 'Price unavailable'}</p>
            {/* LoRA selections (max 2) — only for models that support LoRA */}
            {modelCaps.hasLora && (
              <div className="flex flex-col gap-3">
                {loraSelections.map((sel, idx) => {
                  const available = getAvailableLorasForSlot(idx);
                  return (
                    <div key={idx} className="flex flex-wrap items-end gap-2">
                      <div className="min-w-0 w-full">
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
                      <div className="w-full">
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


            <h3 className="border-t border-border pt-3 font-medium">Advanced for this model</h3>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={autoExpand} onChange={event => setAutoExpand(event.target.checked)} />
              Auto-expand on create
            </label>
            <button onClick={() => expandMutation.mutate(prompt.trim())} disabled={expandMutation.isPending || !prompt.trim()} className="rounded-md border border-input p-2 disabled:opacity-50">
              {expandMutation.isPending ? 'Expanding…' : 'Expand prompt'}
              {generationCosts?.expand_prompt_cost != null && ` (about ${generationCosts.expand_prompt_cost} sparks)`}
            </button>
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

            {spec.image_size?.custom_size && imageSizePreset === 'custom' && (
              <div className="grid gap-3">
                <label className="grid gap-1">Width
                  <input type="number" min={256} max={2048} step={8} value={width} onChange={event => setWidth(Math.max(256, Math.min(2048, Number(event.target.value))))} className="w-full rounded-md border border-input bg-background p-2" />
                </label>
                <label className="grid gap-1">Height
                  <input type="number" min={256} max={2048} step={8} value={height} onChange={event => setHeight(Math.max(256, Math.min(2048, Number(event.target.value))))} className="w-full rounded-md border border-input bg-background p-2" />
                </label>
              </div>
            )}
            {/* Safety Tolerance + Web Search */}
            {(modelCaps.hasSafetyTolerance || modelCaps.hasWebSearch) && (
              <div className="grid grid-cols-1 gap-4">
                {modelCaps.hasSafetyTolerance && (
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Safety Tolerance</label>
                    <select
                      value={safetyTolerance}
                      onChange={(e) => { dirty.current.add('Safety tolerance'); setSafetyTolerance(e.target.value); }}
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

            <div className="grid grid-cols-1 gap-4">
              {/* Steps */}
              {modelCaps.hasStepsGuidance && (
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">
                    Steps: {steps}
                  </label>
                  <Slider
                    min={spec.steps_guidance?.steps?.minimum ?? 1}
                    max={spec.steps_guidance?.steps?.maximum ?? 50}
                    value={steps}
                    onChange={(v) => { dirty.current.add('Steps'); setSteps(v); }}
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
                    min={(spec.steps_guidance?.guidance?.minimum ?? 0) * 10}
                    max={(spec.steps_guidance?.guidance?.maximum ?? 20) * 10}
                    value={Math.round(guidance * 10)}
                    onChange={(v) => { dirty.current.add('Guidance'); setGuidance(v / 10); }}
                    className="w-full"
                  />
                </div>
              )}

              {/* Seed */}
              {spec.seed && <div>
                <label className="block text-xs text-muted-foreground mb-1">Seed</label>
                <input
                  type="text"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value.replace(/\D/g, ''))}
                  placeholder="Random"
                  className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                />
              </div>}
            </div>

          </>
        }
      />
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
                  onClick={() => deleteMutation.mutate(selectedImage.id, { onSuccess: () => setSelectedImageId(null) })}
                  disabled={deleteMutation.isPending}
                  className="ml-auto mr-3 rounded-md border border-input px-2 py-1 text-sm text-destructive disabled:opacity-50"
                >
                  Delete
                </button>
                <button
                  onClick={() => setSelectedImageId(null)}
                  className="p-1 hover:bg-muted rounded-lg transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-4 space-y-4">
                {selectedImage.status === 'completed' && selectedImage.object_key ? (
                  <LibraryImage
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
                    <span><span className="font-medium">Model:</span> {catalog?.generation.find(m => m.key === selectedImage.base_model)?.label || selectedImage.base_model}</span>
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
