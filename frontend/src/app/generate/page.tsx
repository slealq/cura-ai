'use client';

import { useState, useEffect, useRef, Suspense } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { generationApi, settingsApi } from '@/lib/api';
import { Loader2, Sparkles, ChevronDown, ChevronUp, X, KeyRound, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import GeneratedImageCard from '@/components/GeneratedImageCard';
import { cn } from '@/lib/utils';

const SIZE_PRESETS = [
  { label: '1024 x 1024', w: 1024, h: 1024 },
  { label: '768 x 1024', w: 768, h: 1024 },
  { label: '1024 x 768', w: 1024, h: 768 },
  { label: '512 x 512', w: 512, h: 512 },
  { label: '768 x 1344', w: 768, h: 1344 },
  { label: '1344 x 768', w: 1344, h: 768 },
];

const BASE_MODELS = [
  { value: 'flux-dev', label: 'Flux', defaultGuidance: 3.5, hasLora: true, hasStepsGuidance: true, hasWidthHeight: true, usesResolutionAspect: false, hasSafetyTolerance: false, hasWebSearch: false, maxImages: 8 },
  { value: 'qwen-2.5', label: 'Qwen 2.5', defaultGuidance: 4.0, hasLora: true, hasStepsGuidance: true, hasWidthHeight: true, usesResolutionAspect: false, hasSafetyTolerance: false, hasWebSearch: false, maxImages: 8 },
  { value: 'nano-banana-pro', label: 'Nano Banana Pro', defaultGuidance: 0, hasLora: false, hasStepsGuidance: false, hasWidthHeight: false, usesResolutionAspect: true, hasSafetyTolerance: true, hasWebSearch: true, maxImages: 4 },
];

const RESOLUTIONS = [
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
  { value: '1', label: '1 (Strictest)' },
  { value: '2', label: '2' },
  { value: '3', label: '3' },
  { value: '4', label: '4 (Default)' },
  { value: '5', label: '5' },
  { value: '6', label: '6 (Most Permissive)' },
];

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
  const [baseModel, setBaseModel] = useState('flux-dev');
  const [loraSelections, setLoraSelections] = useState<Array<{ id: number; scale: number }>>([]);
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [steps, setSteps] = useState(28);
  const [guidance, setGuidance] = useState(3.5);
  const [seed, setSeed] = useState<string>('');
  const [numImages, setNumImages] = useState(1);
  const [resolution, setResolution] = useState('1K');
  const [aspectRatio, setAspectRatio] = useState('1:1');
  const [safetyTolerance, setSafetyTolerance] = useState('4');
  const [enableWebSearch, setEnableWebSearch] = useState(false);

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

  // Check if fal.ai API key is configured
  const { data: apiKeys } = useQuery({
    queryKey: ['api-keys'],
    queryFn: settingsApi.getApiKeys,
  });
  const falKey = apiKeys?.find((k) => k.provider === 'fal');
  const hasFalKey = falKey?.status === 'active' || falKey?.status === 'quota_exceeded';

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

  const generateMutation = useMutation({
    mutationFn: generationApi.generate,
    onSuccess: (data) => {
      toast.success(`Generation started (${data.generated_image_ids.length} images)`);
      queryClient.invalidateQueries({ queryKey: ['generated-images'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: (err: Error) => {
      toast.error(`Generation failed: ${err.message}`);
    },
  });

  const handleGenerate = () => {
    if (!prompt.trim()) {
      toast.error('Please enter a prompt');
      return;
    }

    const params: Parameters<typeof generationApi.generate>[0] = {
      prompt: prompt.trim(),
      base_model: baseModel,
      num_images: numImages,
    };

    if (negativePrompt.trim()) params.negative_prompt = negativePrompt.trim();
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
    if (modelCaps.hasSafetyTolerance) {
      params.safety_tolerance = safetyTolerance;
    }
    if (modelCaps.hasWebSearch) {
      params.enable_web_search = enableWebSearch;
    }

    generateMutation.mutate(params);
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

      {/* API Key Warning */}
      {!hasFalKey && apiKeys && (
        <div className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded-xl p-6 flex items-start gap-4">
          <KeyRound className="h-6 w-6 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div>
            <h3 className="font-semibold text-amber-900 dark:text-amber-200">fal.ai API key required</h3>
            <p className="text-sm text-amber-700 dark:text-amber-300 mt-1">
              Image generation requires a fal.ai API key. Set one in{' '}
              <Link href="/settings" className="underline font-medium hover:text-amber-900 dark:hover:text-amber-100">
                Settings &rarr; API Keys
              </Link>{' '}
              to enable generation.
            </p>
          </div>
        </div>
      )}

      {/* Generation Form */}
      <section className={cn(
        'bg-card rounded-xl border border-border p-6 space-y-4',
        !hasFalKey && apiKeys && 'opacity-50 pointer-events-none select-none'
      )}>
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
        </div>

        {/* Model selector + LoRA + quick params */}
        <div className="flex flex-wrap gap-4 items-end">
          {/* Base Model */}
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Model</label>
            <div className="flex rounded-lg border border-border overflow-hidden">
              {BASE_MODELS.map((m) => (
                <button
                  key={m.value}
                  onClick={() => {
                    setBaseModel(m.value);
                    setLoraSelections([]);
                    setGuidance(m.defaultGuidance);
                    if (numImages > m.maxImages) setNumImages(m.maxImages);
                  }}
                  className={cn(
                    'px-3 py-2 text-sm font-medium transition-colors',
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
                      <input
                        type="range"
                        min={0}
                        max={20}
                        value={Math.round(sel.scale * 10)}
                        onChange={(e) => updateLoraScale(idx, parseInt(e.target.value) / 10)}
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

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={generateMutation.isPending || !prompt.trim()}
            className="flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 font-medium"
          >
            {generateMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Generate
          </button>
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
            {/* Negative prompt */}
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
                      {SAFETY_LEVELS.map((s) => (
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
                  <input
                    type="range"
                    min={1}
                    max={50}
                    value={steps}
                    onChange={(e) => setSteps(parseInt(e.target.value))}
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
                  <input
                    type="range"
                    min={0}
                    max={200}
                    value={Math.round(guidance * 10)}
                    onChange={(e) => setGuidance(parseInt(e.target.value) / 10)}
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
