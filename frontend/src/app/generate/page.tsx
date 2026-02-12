'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { generationApi } from '@/lib/api';
import { Loader2, Sparkles, ChevronDown, ChevronUp, X } from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import GeneratedImageCard from '@/components/GeneratedImageCard';
import { cn } from '@/lib/utils';
import type { GeneratedImage } from '@/types';

const SIZE_PRESETS = [
  { label: '1024 x 1024', w: 1024, h: 1024 },
  { label: '768 x 1024', w: 768, h: 1024 },
  { label: '1024 x 768', w: 1024, h: 768 },
  { label: '512 x 512', w: 512, h: 512 },
  { label: '768 x 1344', w: 768, h: 1344 },
  { label: '1344 x 768', w: 1344, h: 768 },
];

const BASE_MODELS = [
  { value: 'flux-dev', label: 'Flux', defaultGuidance: 3.5 },
  { value: 'qwen-2.5', label: 'Qwen 2.5', defaultGuidance: 4.0 },
];

export default function GeneratePage() {
  const queryClient = useQueryClient();

  // Form state
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [baseModel, setBaseModel] = useState('flux-dev');
  const [loraId, setLoraId] = useState<number | undefined>(undefined);
  const [loraScale, setLoraScale] = useState(1.0);
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [steps, setSteps] = useState(28);
  const [guidance, setGuidance] = useState(3.5);
  const [seed, setSeed] = useState<string>('');
  const [numImages, setNumImages] = useState(1);

  // Full-size modal
  const [selectedImage, setSelectedImage] = useState<GeneratedImage | null>(null);

  // Fetch completed LoRA models filtered by base model
  const { data: loraList } = useQuery({
    queryKey: ['lora-models', 'completed', baseModel],
    queryFn: () => generationApi.listLora({ status: 'completed', base_model: baseModel }),
  });

  // Fetch generated images with polling
  const { data: generatedImages, isLoading: imagesLoading } = useQuery({
    queryKey: ['generated-images'],
    queryFn: () => generationApi.listImages({ limit: 100 }),
    refetchInterval: 3000,
  });

  // Generate mutation
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
    generateMutation.mutate({
      prompt: prompt.trim(),
      negative_prompt: negativePrompt.trim() || undefined,
      lora_model_id: loraId,
      lora_scale: loraId ? loraScale : undefined,
      base_model: baseModel,
      width,
      height,
      num_inference_steps: steps,
      guidance_scale: guidance,
      seed: seed ? parseInt(seed) : undefined,
      num_images: numImages,
    });
  };

  const handleSizePreset = (w: number, h: number) => {
    setWidth(w);
    setHeight(h);
  };

  const images = generatedImages?.items || [];

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Generate</h1>
        <p className="text-muted-foreground mt-1">
          Create images with your trained LoRAs
        </p>
      </div>

      {/* Generation Form */}
      <section className="bg-white rounded-xl border border-border p-6 space-y-4">
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
                    setLoraId(undefined);
                    setGuidance(m.defaultGuidance);
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

          {/* LoRA */}
          <div className="min-w-[200px]">
            <label className="block text-xs text-muted-foreground mb-1">LoRA Model</label>
            <select
              value={loraId ?? ''}
              onChange={(e) => setLoraId(e.target.value ? parseInt(e.target.value) : undefined)}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm"
            >
              <option value="">No LoRA</option>
              {loraList?.items.map((lora) => (
                <option key={lora.id} value={lora.id}>
                  {lora.name} ({lora.trigger_word})
                </option>
              ))}
            </select>
          </div>

          {/* LoRA scale */}
          {loraId && (
            <div className="w-32">
              <label className="block text-xs text-muted-foreground mb-1">
                LoRA Scale: {loraScale.toFixed(1)}
              </label>
              <input
                type="range"
                min={0}
                max={20}
                value={Math.round(loraScale * 10)}
                onChange={(e) => setLoraScale(parseInt(e.target.value) / 10)}
                className="w-full"
              />
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
              {[1, 2, 4, 8].map((n) => (
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

            {/* Size presets */}
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

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Steps */}
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

              {/* Guidance */}
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
                onClick={() => setSelectedImage(img)}
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
            onClick={() => setSelectedImage(null)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-white rounded-xl shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between p-4 border-b border-border">
                <h3 className="font-semibold">Generated Image #{selectedImage.id}</h3>
                <button
                  onClick={() => setSelectedImage(null)}
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
                    {selectedImage.lora_model_name && selectedImage.lora_model_id && (
                      <span>
                        <span className="font-medium">LoRA:</span>{' '}
                        <Link href="/models" className="text-primary hover:underline" onClick={() => setSelectedImage(null)}>
                          {selectedImage.lora_model_name}
                        </Link>
                      </span>
                    )}
                    {selectedImage.generation_params && (
                      <>
                        <span><span className="font-medium">Steps:</span> {(selectedImage.generation_params as Record<string, unknown>).num_inference_steps as number}</span>
                        <span><span className="font-medium">Guidance:</span> {(selectedImage.generation_params as Record<string, unknown>).guidance_scale as number}</span>
                        {(selectedImage.generation_params as Record<string, unknown>).actual_seed && (
                          <span><span className="font-medium">Seed:</span> {(selectedImage.generation_params as Record<string, unknown>).actual_seed as number}</span>
                        )}
                      </>
                    )}
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
