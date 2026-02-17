'use client';

import { useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { editApi, settingsApi } from '@/lib/api';
import { Loader2, Pencil, ChevronDown, ChevronUp, X, KeyRound, Upload, ImageIcon } from 'lucide-react';
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
];

interface SourceImage {
  type: 'gallery' | 'generated' | 'upload';
  id?: number;
  key?: string;
  previewUrl?: string;
  name?: string;
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

  // Source images state
  const [sources, setSources] = useState<SourceImage[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Full-size modal
  const [selectedImageId, setSelectedImageId] = useState<number | null>(null);

  // Check fal.ai API key
  const { data: apiKeys } = useQuery({
    queryKey: ['api-keys'],
    queryFn: settingsApi.getApiKeys,
  });
  const falKey = apiKeys?.find((k) => k.provider === 'fal');
  const hasFalKey = falKey?.status === 'active' || falKey?.status === 'quota_exceeded';

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
    if (!prompt.trim()) {
      toast.error('Please enter a prompt');
      return;
    }
    if (sources.length === 0) {
      toast.error('Please add at least one source image');
      return;
    }

    const params: Parameters<typeof editApi.edit>[0] = {
      prompt: prompt.trim(),
      negative_prompt: negativePrompt.trim() || undefined,
      edit_model: editModel,
      num_images: numImages,
      output_format: outputFormat,
      enable_prompt_expansion: enablePromptExpansion,
      enable_safety_checker: enableSafetyChecker,
    };

    // Collect source IDs by type
    const galleryIds = sources.filter((s) => s.type === 'gallery').map((s) => s.id!);
    const generatedIds = sources.filter((s) => s.type === 'generated').map((s) => s.id!);
    const uploadKeys = sources.filter((s) => s.type === 'upload').map((s) => s.key!);

    if (galleryIds.length > 0) params.source_image_ids = galleryIds;
    if (generatedIds.length > 0) params.source_generated_ids = generatedIds;
    if (uploadKeys.length > 0) params.source_upload_keys = uploadKeys;

    if (useCustomSize) {
      params.image_size = { width: customWidth, height: customHeight };
    } else {
      params.image_size = imageSize;
    }

    if (seed) params.seed = parseInt(seed);

    editMutation.mutate(params);
  };

  const removeSource = (index: number) => {
    setSources(sources.filter((_, i) => i !== index));
  };

  const handleFileUpload = useCallback(async (files: FileList | File[]) => {
    const maxSources = 3;
    const remaining = maxSources - sources.length;
    if (remaining <= 0) {
      toast.error('Maximum 3 source images');
      return;
    }

    const filesToProcess = Array.from(files).slice(0, remaining);
    setUploading(true);

    try {
      for (const file of filesToProcess) {
        if (file.size > 10 * 1024 * 1024) {
          toast.error(`${file.name} is too large (max 10MB)`);
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
  }, [sources.length]);

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

  const handlePickerSelect = (sourceType: 'gallery' | 'generated', ids: number[]) => {
    // Remove existing selections of this type
    const otherSources = sources.filter((s) => s.type !== sourceType);
    const newSources = ids.map((id) => ({
      type: sourceType as 'gallery' | 'generated',
      id,
    }));
    setSources([...otherSources, ...newSources]);
  };

  const images = editedImages?.items || [];
  const selectedImage = selectedImageId != null
    ? images.find((img) => img.id === selectedImageId) ?? null
    : null;

  const selectedGalleryIds = sources.filter((s) => s.type === 'gallery').map((s) => s.id!);
  const selectedGeneratedIds = sources.filter((s) => s.type === 'generated').map((s) => s.id!);

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Edit</h1>
        <p className="text-muted-foreground mt-1">
          Edit images with AI using source images and prompts
        </p>
      </div>

      {/* API Key Warning */}
      {!hasFalKey && apiKeys && (
        <div className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded-xl p-6 flex items-start gap-4">
          <KeyRound className="h-6 w-6 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div>
            <h3 className="font-semibold text-amber-900 dark:text-amber-200">fal.ai API key required</h3>
            <p className="text-sm text-amber-700 dark:text-amber-300 mt-1">
              Image editing requires a fal.ai API key. Set one in{' '}
              <Link href="/settings" className="underline font-medium hover:text-amber-900 dark:hover:text-amber-100">
                Settings &rarr; API Keys
              </Link>{' '}
              to enable editing.
            </p>
          </div>
        </div>
      )}

      {/* Edit Form */}
      <section
        className={cn(
          'bg-card rounded-xl border border-border p-6 space-y-4',
          !hasFalKey && apiKeys && 'opacity-50 pointer-events-none select-none'
        )}
        onPaste={handlePaste}
      >
        {/* Source Images */}
        <div>
          <label className="block text-sm font-medium mb-2">Source Images</label>
          <div className="flex flex-wrap gap-3 items-start">
            {/* Existing source previews */}
            {sources.map((src, idx) => (
              <div key={idx} className="relative group w-20 h-20">
                <div className="w-full h-full rounded-lg border border-border overflow-hidden bg-muted/30">
                  {src.previewUrl ? (
                    <img src={src.previewUrl} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <ImageIcon className="h-6 w-6 text-muted-foreground" />
                    </div>
                  )}
                </div>
                <button
                  onClick={() => removeSource(idx)}
                  className="absolute -top-1.5 -right-1.5 p-0.5 rounded-full bg-red-500 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X className="h-3 w-3" />
                </button>
                <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[9px] text-center py-0.5 rounded-b-lg">
                  {src.type === 'gallery' ? `#${src.id}` : src.type === 'generated' ? `Gen #${src.id}` : src.name?.slice(0, 8) || 'Upload'}
                </span>
              </div>
            ))}

            {/* Add source buttons */}
            {sources.length < 3 && (
              <>
                {/* Drop zone / upload */}
                <label
                  className="w-20 h-20 rounded-lg border-2 border-dashed border-border hover:border-primary/50 flex flex-col items-center justify-center cursor-pointer transition-colors"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={handleDrop}
                >
                  {uploading ? (
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  ) : (
                    <>
                      <Upload className="h-4 w-4 text-muted-foreground" />
                      <span className="text-[9px] text-muted-foreground mt-0.5">Upload</span>
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
                  className="w-20 h-20 rounded-lg border-2 border-dashed border-border hover:border-primary/50 flex flex-col items-center justify-center transition-colors"
                >
                  <ImageIcon className="h-4 w-4 text-muted-foreground" />
                  <span className="text-[9px] text-muted-foreground mt-0.5">Browse</span>
                </button>
              </>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Add 1-3 source images. Drag &amp; drop, paste, upload, or browse gallery/generated.
          </p>
        </div>

        {/* Prompt */}
        <div>
          <label className="block text-sm font-medium mb-1">
            Prompt
            <span className="text-muted-foreground font-normal ml-2">
              {prompt.length}/800
            </span>
          </label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value.slice(0, 800))}
            placeholder="Describe how you want to edit the image..."
            className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                handleEdit();
              }
            }}
          />
        </div>

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

          {/* Num images */}
          <div className="w-24">
            <label className="block text-xs text-muted-foreground mb-1">Images</label>
            <select
              value={numImages}
              onChange={(e) => setNumImages(parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm"
            >
              {[1, 2, 3, 4, 6].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>

          {/* Edit button */}
          <button
            onClick={handleEdit}
            disabled={editMutation.isPending || !prompt.trim() || sources.length === 0}
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
                onChange={(e) => setNegativePrompt(e.target.value.slice(0, 500))}
                placeholder="Things to avoid..."
                className="w-full px-3 py-2 border border-border rounded-lg text-sm"
              />
            </div>

            {/* Size presets */}
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

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
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
            <div className="flex flex-wrap gap-6">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={enablePromptExpansion}
                  onChange={(e) => setEnablePromptExpansion(e.target.checked)}
                  className="rounded"
                />
                Prompt expansion
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={enableSafetyChecker}
                  onChange={(e) => setEnableSafetyChecker(e.target.checked)}
                  className="rounded"
                />
                Safety checker
              </label>
            </div>
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
                    {selectedImage.generation_params && (
                      <>
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

      {/* Image Picker Modal */}
      <ImagePickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={handlePickerSelect}
        selectedGalleryIds={selectedGalleryIds}
        selectedGeneratedIds={selectedGeneratedIds}
        maxSelection={3 - sources.filter((s) => s.type === 'upload').length}
      />
    </div>
  );
}
