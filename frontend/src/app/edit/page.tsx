'use client';

import { useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { editApi } from '@/lib/api';
import { Loader2, Pencil, ChevronDown, ChevronUp, X, Upload, ImageIcon } from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import GeneratedImageCard from '@/components/GeneratedImageCard';
import ImagePickerModal from '@/components/ImagePickerModal';
import { cn } from '@/lib/utils';

const SIZE_PRESETS = [
  { label: 'Square HD', value: 'square_hd' },
  { label: 'Square', value: 'square' },
  { label: 'Portrait 4:3', value: 'portrait_4_3' },
  { label: 'Portrait 16:9', value: 'portrait_16_9' },
  { label: 'Landscape 4:3', value: 'landscape_4_3' },
  { label: 'Landscape 16:9', value: 'landscape_16_9' },
];

const EDIT_MODELS = [
  { value: 'qwen-image-max-edit', label: 'Qwen Image Max Edit' },
  { value: 'kling-image', label: 'Kling Image' },
  { value: 'wan-25', label: 'Wan 2.5' },
  { value: 'grok-imagine', label: 'Grok Imagine' },
  { value: 'nano-banana-pro-edit', label: 'Nano Banana Pro Edit' },
  { value: 'face-swap', label: 'Face Swap' },
];

const KLING_RESOLUTIONS = [
  { value: '1K', label: '1K' },
  { value: '2K', label: '2K' },
  { value: '4K', label: '4K' },
];

const KLING_ASPECT_RATIOS = [
  { value: 'auto', label: 'Auto' },
  { value: '1:1', label: '1:1' },
  { value: '16:9', label: '16:9' },
  { value: '9:16', label: '9:16' },
  { value: '4:3', label: '4:3' },
  { value: '3:4', label: '3:4' },
  { value: '3:2', label: '3:2' },
  { value: '2:3', label: '2:3' },
  { value: '21:9', label: '21:9' },
];

const NANO_ASPECT_RATIOS = [
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

interface SourceImage {
  type: 'gallery' | 'generated' | 'upload';
  id?: number;
  key?: string;
  previewUrl?: string;
  name?: string;
}

function formatDuration(createdAt: string, completedAt: string | null): string | null {
  if (!completedAt) return null;
  const ms = new Date(completedAt).getTime() - new Date(createdAt).getTime();
  if (ms < 0) return null;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes}m ${secs}s`;
}

export default function EditPage() {
  const queryClient = useQueryClient();

  // Form state
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [editModel, setEditModel] = useState('qwen-image-max-edit');
  const [imageSize, setImageSize] = useState<string>('square_hd');
  const [customWidth, setCustomWidth] = useState(1024);
  const [customHeight, setCustomHeight] = useState(1024);
  const [useCustomSize, setUseCustomSize] = useState(false);
  const [numImages, setNumImages] = useState(1);
  const [seed, setSeed] = useState<string>('');
  const [outputFormat, setOutputFormat] = useState('png');
  const [enablePromptExpansion, setEnablePromptExpansion] = useState(true);
  const [enableSafetyChecker, setEnableSafetyChecker] = useState(true);
  // Kling-specific state
  const [resolution, setResolution] = useState('1K');
  const [aspectRatio, setAspectRatio] = useState('auto');
  // Nano Banana Pro state
  const [safetyTolerance, setSafetyTolerance] = useState('4');
  const [enableWebSearch, setEnableWebSearch] = useState(false);
  // Face swap state
  const [enableOcclusionPrevention, setEnableOcclusionPrevention] = useState(false);

  const isKling = editModel === 'kling-image';
  const isFaceSwap = editModel === 'face-swap';

  // Model capability flags
  const MODEL_CAPS: Record<string, { maxSources: number; maxImages: number; hasNegativePrompt: boolean; hasPromptExpansion: boolean; hasSafetyChecker: boolean; usesResolution: boolean; hasImageSize: boolean; hasSeed: boolean; maxPromptLen: number; hasSafetyTolerance: boolean; hasWebSearch: boolean }> = {
    'qwen-image-max-edit': { maxSources: 3, maxImages: 6, hasNegativePrompt: true, hasPromptExpansion: true, hasSafetyChecker: true, usesResolution: false, hasImageSize: true, hasSeed: true, maxPromptLen: 800, hasSafetyTolerance: false, hasWebSearch: false },
    'kling-image': { maxSources: 10, maxImages: 9, hasNegativePrompt: false, hasPromptExpansion: false, hasSafetyChecker: false, usesResolution: true, hasImageSize: false, hasSeed: true, maxPromptLen: 2500, hasSafetyTolerance: false, hasWebSearch: false },
    'wan-25': { maxSources: 2, maxImages: 4, hasNegativePrompt: true, hasPromptExpansion: false, hasSafetyChecker: true, usesResolution: false, hasImageSize: true, hasSeed: true, maxPromptLen: 2000, hasSafetyTolerance: false, hasWebSearch: false },
    'grok-imagine': { maxSources: 1, maxImages: 4, hasNegativePrompt: false, hasPromptExpansion: false, hasSafetyChecker: false, usesResolution: false, hasImageSize: false, hasSeed: false, maxPromptLen: 8000, hasSafetyTolerance: false, hasWebSearch: false },
    'nano-banana-pro-edit': { maxSources: 14, maxImages: 4, hasNegativePrompt: false, hasPromptExpansion: false, hasSafetyChecker: false, usesResolution: true, hasImageSize: false, hasSeed: true, maxPromptLen: 50000, hasSafetyTolerance: true, hasWebSearch: true },
    'face-swap': { maxSources: 2, maxImages: 1, hasNegativePrompt: false, hasPromptExpansion: false, hasSafetyChecker: false, usesResolution: false, hasImageSize: false, hasSeed: false, maxPromptLen: 0, hasSafetyTolerance: false, hasWebSearch: false },
  };
  const caps = MODEL_CAPS[editModel] || MODEL_CAPS['qwen-image-max-edit'];

  // Source images state
  const [sources, setSources] = useState<SourceImage[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Full-size modal
  const [selectedImageId, setSelectedImageId] = useState<number | null>(null);

  // Fetch edited images with polling
  const { data: editedImages, isLoading: imagesLoading } = useQuery({
    queryKey: ['edited-images'],
    queryFn: () => editApi.listImages({ limit: 100 }),
    refetchInterval: 3000,
  });

  // Edit mutation
  const editMutation = useMutation({
    mutationFn: editApi.edit,
    onSuccess: (data) => {
      toast.success(`Edit started (${data.generated_image_ids.length} images)`);
      queryClient.invalidateQueries({ queryKey: ['edited-images'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: (err: Error) => {
      toast.error(`Edit failed: ${err.message}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: editApi.deleteImage,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['edited-images'] });
    },
    onError: (err: Error) => {
      toast.error(`Delete failed: ${err.message}`);
    },
  });

  const handleEdit = () => {
    if (isFaceSwap) {
      if (sources.length !== 2) {
        toast.error('Face swap requires exactly 2 images: source face and target image');
        return;
      }
    } else {
      if (!prompt.trim()) {
        toast.error('Please enter a prompt');
        return;
      }
      if (sources.length === 0) {
        toast.error('Please add at least one source image');
        return;
      }
    }

    const params: Parameters<typeof editApi.edit>[0] = {
      edit_model: editModel,
      num_images: isFaceSwap ? 1 : numImages,
    };

    if (isFaceSwap) {
      if (enableOcclusionPrevention) {
        params.enable_occlusion_prevention = true;
      }
    } else {
      params.prompt = prompt.trim();
      params.output_format = outputFormat;

      if (caps.usesResolution) {
        params.resolution = resolution;
        params.aspect_ratio = aspectRatio;
      } else if (caps.hasImageSize) {
        if (useCustomSize) {
          params.image_size = { width: customWidth, height: customHeight };
        } else {
          params.image_size = imageSize;
        }
      }
      if (caps.hasNegativePrompt && negativePrompt.trim()) {
        params.negative_prompt = negativePrompt.trim();
      }
      if (caps.hasPromptExpansion) {
        params.enable_prompt_expansion = enablePromptExpansion;
      }
      if (caps.hasSafetyChecker) {
        params.enable_safety_checker = enableSafetyChecker;
      }
      if (caps.hasSafetyTolerance) {
        params.safety_tolerance = safetyTolerance;
      }
      if (caps.hasWebSearch) {
        params.enable_web_search = enableWebSearch;
      }
      if (caps.hasSeed && seed) params.seed = parseInt(seed);
    }

    // Collect source IDs by type
    const galleryIds = sources.filter((s) => s.type === 'gallery').map((s) => s.id!);
    const generatedIds = sources.filter((s) => s.type === 'generated').map((s) => s.id!);
    const uploadKeys = sources.filter((s) => s.type === 'upload').map((s) => s.key!);

    if (galleryIds.length > 0) params.source_image_ids = galleryIds;
    if (generatedIds.length > 0) params.source_generated_ids = generatedIds;
    if (uploadKeys.length > 0) params.source_upload_keys = uploadKeys;

    editMutation.mutate(params);
  };

  const removeSource = (index: number) => {
    setSources(sources.filter((_, i) => i !== index));
  };

  const maxSources = caps.maxSources;

  const handleFileUpload = useCallback(async (files: FileList | File[]) => {
    const remaining = maxSources - sources.length;
    if (remaining <= 0) {
      toast.error(`Maximum ${maxSources} source images`);
      return;
    }

    const filesToProcess = Array.from(files).slice(0, remaining);
    setUploading(true);

    try {
      for (const file of filesToProcess) {
        if (file.size > 30 * 1024 * 1024) {
          toast.error(`${file.name} is too large (max 30MB)`);
          continue;
        }
        const result = await editApi.uploadSource(file);
        const previewUrl = URL.createObjectURL(file);
        setSources((prev) => [
          ...prev,
          { type: 'upload', key: result.object_key, previewUrl, name: file.name },
        ]);
      }
    } catch (err) {
      toast.error(`Upload failed: ${(err as Error).message}`);
    } finally {
      setUploading(false);
    }
  }, [sources.length, maxSources]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer.files.length > 0) {
        handleFileUpload(e.dataTransfer.files);
      }
    },
    [handleFileUpload]
  );

  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = e.clipboardData.items;
      const imageFiles: File[] = [];
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.startsWith('image/')) {
          const file = items[i].getAsFile();
          if (file) imageFiles.push(file);
        }
      }
      if (imageFiles.length > 0) {
        e.preventDefault();
        handleFileUpload(imageFiles);
      }
    },
    [handleFileUpload]
  );

  const handlePickerDone = (items: import('@/components/ImagePickerModal').PickedImage[]) => {
    const newSources: SourceImage[] = items.map((item) => ({
      type: item.type,
      id: item.id,
      previewUrl: item.previewUrl,
    }));
    setSources((prev) => [...prev, ...newSources]);
  };

  const images = editedImages?.items || [];
  const selectedImage = selectedImageId != null
    ? images.find((img) => img.id === selectedImageId) ?? null
    : null;

  const alreadySelectedIds = sources.filter((s) => s.type === 'gallery' || s.type === 'generated').map((s) => s.id!);

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Edit</h1>
        <p className="text-muted-foreground mt-1">
          Edit images with AI using source images and prompts
        </p>
      </div>

      {/* Edit Form */}
      <section
        className="bg-card rounded-xl border border-border p-6 space-y-4"
        onPaste={handlePaste}
      >
        {/* Source Images */}
        <div>
          <label className="block text-sm font-medium mb-2">
            {isFaceSwap ? 'Face Swap Images' : 'Source Images'}
          </label>
          <div className="flex flex-wrap gap-3 items-start">
            {/* Existing source previews */}
            {sources.map((src, idx) => (
              <div key={idx} className="relative group w-32 h-32">
                <div className="w-full h-full rounded-lg border border-border overflow-hidden bg-muted/30">
                  {src.previewUrl ? (
                    <img src={src.previewUrl} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <ImageIcon className="h-8 w-8 text-muted-foreground" />
                    </div>
                  )}
                </div>
                <button
                  onClick={() => removeSource(idx)}
                  className="absolute -top-1.5 -right-1.5 p-0.5 rounded-full bg-red-500 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
                <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[10px] text-center py-0.5 rounded-b-lg">
                  {isFaceSwap
                    ? (idx === 0 ? 'Source Face' : 'Target')
                    : src.type === 'gallery' ? `#${src.id}` : src.type === 'generated' ? `Gen #${src.id}` : src.name?.slice(0, 12) || 'Upload'}
                </span>
              </div>
            ))}

            {/* Add source buttons */}
            {sources.length < maxSources && (
              <>
                {/* Drop zone / upload */}
                <label
                  className="w-32 h-32 rounded-lg border-2 border-dashed border-border hover:border-primary/50 flex flex-col items-center justify-center cursor-pointer transition-colors"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={handleDrop}
                >
                  {uploading ? (
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  ) : (
                    <>
                      <Upload className="h-5 w-5 text-muted-foreground" />
                      <span className="text-xs text-muted-foreground mt-1">Upload</span>
                    </>
                  )}
                  <input
                    type="file"
                    accept="image/*"
                    multiple
                    className="hidden"
                    onChange={(e) => e.target.files && handleFileUpload(e.target.files)}
                  />
                </label>

                {/* Browse button */}
                <button
                  onClick={() => setPickerOpen(true)}
                  className="w-32 h-32 rounded-lg border-2 border-dashed border-border hover:border-primary/50 flex flex-col items-center justify-center transition-colors"
                >
                  <ImageIcon className="h-5 w-5 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground mt-1">Browse</span>
                </button>
              </>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {isFaceSwap
              ? 'Add exactly 2 images: first the source face, then the target image to swap the face onto.'
              : <>
                  Add 1-{maxSources} source images. Drag &amp; drop, paste, upload, or browse gallery/generated.
                  {isKling && ' Reference images in your prompt using @Image1, @Image2, etc.'}
                  {editModel === 'wan-25' && ' Max 2 source images (1 for single edit, 2 for multi-reference).'}
                </>
            }
          </p>
        </div>

        {/* Prompt (hidden for face swap) */}
        {!isFaceSwap && (
          <div>
            <label className="block text-sm font-medium mb-1">
              Prompt
              <span className="text-muted-foreground font-normal ml-2">
                {prompt.length}/{caps.maxPromptLen}
              </span>
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value.slice(0, caps.maxPromptLen))}
              placeholder={isKling
                ? "Use @Image1 to reference your source image. e.g. 'Transform @Image1 into a watercolor painting'"
                : "Describe how you want to edit the image..."}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  handleEdit();
                }
              }}
            />
          </div>
        )}

        {/* Face swap occlusion toggle */}
        {isFaceSwap && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enableOcclusionPrevention}
              onChange={(e) => setEnableOcclusionPrevention(e.target.checked)}
              className="rounded"
            />
            Occlusion prevention
            <span className="text-xs text-muted-foreground">(handles faces covered by hands/objects, costs 2x)</span>
          </label>
        )}

        {/* Controls row */}
        <div className="flex flex-wrap gap-4 items-end">
          {/* Edit model */}
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Model</label>
            <select
              value={editModel}
              onChange={(e) => setEditModel(e.target.value)}
              className="px-3 py-2 border border-border rounded-lg text-sm"
            >
              {EDIT_MODELS.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>

          {/* Num images (hidden for face swap) */}
          {!isFaceSwap && (
            <div className="w-24">
              <label className="block text-xs text-muted-foreground mb-1">Images</label>
              <select
                value={numImages}
                onChange={(e) => setNumImages(parseInt(e.target.value))}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm"
              >
                {[1, 2, 3, 4, 6, 9].filter((n) => n <= caps.maxImages).map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </div>
          )}

          {/* Edit button */}
          <button
            onClick={handleEdit}
            disabled={editMutation.isPending || (!isFaceSwap && !prompt.trim()) || sources.length === 0 || (isFaceSwap && sources.length !== 2)}
            className="flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 font-medium"
          >
            {editMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Pencil className="h-4 w-4" />
            )}
            Edit
          </button>
        </div>

        {/* Advanced toggle (hidden for face swap) */}
        {!isFaceSwap && (
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            Advanced Parameters
          </button>
        )}

        {/* Advanced params */}
        {!isFaceSwap && showAdvanced && (
          <div className="border border-border rounded-lg p-4 space-y-4">
            {/* Negative prompt */}
            {caps.hasNegativePrompt && (
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Negative Prompt</label>
                <input
                  type="text"
                  value={negativePrompt}
                  onChange={(e) => setNegativePrompt(e.target.value.slice(0, 500))}
                  placeholder="Things to avoid..."
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                />
              </div>
            )}

            {/* Resolution + Aspect Ratio (Kling) */}
            {caps.usesResolution && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Resolution</label>
                  <div className="flex gap-2">
                    {KLING_RESOLUTIONS.map((r) => (
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
                    {(editModel === 'nano-banana-pro-edit' ? NANO_ASPECT_RATIOS : KLING_ASPECT_RATIOS).map((ar) => (
                      <option key={ar.value} value={ar.value}>{ar.label}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            {/* Size presets (Qwen/Wan) */}
            {caps.hasImageSize && (
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Image Size</label>
                <div className="flex flex-wrap gap-2">
                  {SIZE_PRESETS.map((preset) => (
                    <button
                      key={preset.value}
                      onClick={() => {
                        setImageSize(preset.value);
                        setUseCustomSize(false);
                      }}
                      className={cn(
                        'px-3 py-1.5 text-xs border rounded-lg transition-colors',
                        !useCustomSize && imageSize === preset.value
                          ? 'border-primary bg-primary/5 text-primary'
                          : 'border-border hover:bg-muted'
                      )}
                    >
                      {preset.label}
                    </button>
                  ))}
                  <button
                    onClick={() => setUseCustomSize(true)}
                    className={cn(
                      'px-3 py-1.5 text-xs border rounded-lg transition-colors',
                      useCustomSize
                        ? 'border-primary bg-primary/5 text-primary'
                        : 'border-border hover:bg-muted'
                    )}
                  >
                    Custom
                  </button>
                </div>
                {useCustomSize && (
                  <div className="flex gap-2 mt-2">
                    <div>
                      <label className="text-xs text-muted-foreground">Width</label>
                      <input
                        type="number"
                        value={customWidth}
                        onChange={(e) => setCustomWidth(parseInt(e.target.value) || 1024)}
                        min={256}
                        max={2048}
                        className="w-24 px-2 py-1 border border-border rounded-lg text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground">Height</label>
                      <input
                        type="number"
                        value={customHeight}
                        onChange={(e) => setCustomHeight(parseInt(e.target.value) || 1024)}
                        min={256}
                        max={2048}
                        className="w-24 px-2 py-1 border border-border rounded-lg text-sm"
                      />
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Seed */}
              {caps.hasSeed && (
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
              )}

              {/* Output format */}
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Format</label>
                <select
                  value={outputFormat}
                  onChange={(e) => setOutputFormat(e.target.value)}
                  className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                >
                  <option value="png">PNG</option>
                  <option value="jpeg">JPEG</option>
                  <option value="webp">WebP</option>
                </select>
              </div>
            </div>

            {/* Toggles */}
            {(caps.hasPromptExpansion || caps.hasSafetyChecker) && (
              <div className="flex flex-wrap gap-6">
                {caps.hasPromptExpansion && (
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={enablePromptExpansion}
                      onChange={(e) => setEnablePromptExpansion(e.target.checked)}
                      className="rounded"
                    />
                    Prompt expansion
                  </label>
                )}
                {caps.hasSafetyChecker && (
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={enableSafetyChecker}
                      onChange={(e) => setEnableSafetyChecker(e.target.checked)}
                      className="rounded"
                    />
                    Safety checker
                  </label>
                )}
              </div>
            )}

            {/* Safety Tolerance + Web Search */}
            {(caps.hasSafetyTolerance || caps.hasWebSearch) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {caps.hasSafetyTolerance && (
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
                {caps.hasWebSearch && (
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
          </div>
        )}
      </section>

      {/* Edited Images Grid */}
      <section>
        <h2 className="font-semibold mb-3">
          Edited Images
          {editedImages && <span className="text-muted-foreground font-normal ml-2">({editedImages.total})</span>}
        </h2>
        {imagesLoading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : images.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground">
            <Pencil className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p>No edited images yet</p>
            <p className="text-sm mt-1">Add source images and a prompt above, then click Edit</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {images.map((img) => (
              <div key={img.id} className="relative">
                <GeneratedImageCard
                  image={img}
                  onClick={() => setSelectedImageId(img.id)}
                  onDelete={(id) => deleteMutation.mutate(id)}
                />
                {img.status === 'completed' && img.completed_at && (
                  <div className="absolute bottom-1 right-1 z-10 pointer-events-none">
                    <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-black/60 text-white">
                      {formatDuration(img.created_at, img.completed_at)}
                    </span>
                  </div>
                )}
              </div>
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
                <h3 className="font-semibold">Edited Image #{selectedImage.id}</h3>
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
                    src={editApi.getImageUrl(selectedImage.id)}
                    alt={selectedImage.prompt}
                    className="max-w-full mx-auto rounded-lg"
                  />
                ) : (
                  <div className="flex items-center justify-center h-64 bg-muted/30 rounded-lg">
                    {selectedImage.status === 'failed' ? (
                      <p className="text-red-600 text-sm">{selectedImage.error_message || 'Edit failed'}</p>
                    ) : (
                      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                    )}
                  </div>
                )}
                <div className="space-y-3 text-sm">
                  <div>
                    <span className="font-medium">Prompt:</span>
                    <p className="text-muted-foreground mt-0.5">{selectedImage.prompt}</p>
                  </div>
                  {selectedImage.negative_prompt && (
                    <div>
                      <span className="font-medium">Negative Prompt:</span>
                      <p className="text-muted-foreground mt-0.5">{selectedImage.negative_prompt}</p>
                    </div>
                  )}
                  {(() => {
                    const gp = (selectedImage.generation_params || {}) as Record<string, unknown>;
                    const duration = formatDuration(selectedImage.created_at, selectedImage.completed_at);
                    const modelLabel = EDIT_MODELS.find((m) => m.value === selectedImage.base_model)?.label || selectedImage.base_model;
                    return (
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2 bg-muted/30 rounded-lg p-3">
                        <div>
                          <span className="text-xs text-muted-foreground">Model</span>
                          <p className="font-medium">{modelLabel}</p>
                        </div>
                        {selectedImage.width != null && selectedImage.height != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Output Size</span>
                            <p className="font-medium">{selectedImage.width} x {selectedImage.height}</p>
                          </div>
                        )}
                        {duration && (
                          <div>
                            <span className="text-xs text-muted-foreground">Duration</span>
                            <p className="font-medium">{duration}</p>
                          </div>
                        )}
                        {gp.actual_seed != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Seed</span>
                            <p className="font-medium">{String(gp.actual_seed)}</p>
                          </div>
                        )}
                        {typeof gp.image_size === 'string' && (
                          <div>
                            <span className="text-xs text-muted-foreground">Size Preset</span>
                            <p className="font-medium">{SIZE_PRESETS.find((p) => p.value === gp.image_size)?.label || String(gp.image_size)}</p>
                          </div>
                        )}
                        {typeof gp.image_size === 'object' && gp.image_size !== null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Requested Size</span>
                            <p className="font-medium">{(gp.image_size as { width: number; height: number }).width} x {(gp.image_size as { width: number; height: number }).height}</p>
                          </div>
                        )}
                        {'resolution' in gp && gp.resolution != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Resolution</span>
                            <p className="font-medium">{String(gp.resolution)}</p>
                          </div>
                        )}
                        {'aspect_ratio' in gp && gp.aspect_ratio != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Aspect Ratio</span>
                            <p className="font-medium">{String(gp.aspect_ratio)}</p>
                          </div>
                        )}
                        {'output_format' in gp && gp.output_format != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Format</span>
                            <p className="font-medium uppercase">{String(gp.output_format)}</p>
                          </div>
                        )}
                        {'enable_prompt_expansion' in gp && gp.enable_prompt_expansion != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Prompt Expansion</span>
                            <p className="font-medium">{gp.enable_prompt_expansion ? 'On' : 'Off'}</p>
                          </div>
                        )}
                        {'enable_safety_checker' in gp && gp.enable_safety_checker != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Safety Checker</span>
                            <p className="font-medium">{gp.enable_safety_checker ? 'On' : 'Off'}</p>
                          </div>
                        )}
                        {'safety_tolerance' in gp && gp.safety_tolerance != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Safety Tolerance</span>
                            <p className="font-medium">{String(gp.safety_tolerance)}</p>
                          </div>
                        )}
                        {'enable_web_search' in gp && gp.enable_web_search != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Web Search</span>
                            <p className="font-medium">{gp.enable_web_search ? 'On' : 'Off'}</p>
                          </div>
                        )}
                        {'enable_occlusion_prevention' in gp && gp.enable_occlusion_prevention != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Occlusion Prevention</span>
                            <p className="font-medium">{gp.enable_occlusion_prevention ? 'On' : 'Off'}</p>
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Image Picker Modal */}
      <ImagePickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onDone={handlePickerDone}
        alreadySelectedIds={alreadySelectedIds}
        maxSelection={maxSources}
      />
    </div>
  );
}
