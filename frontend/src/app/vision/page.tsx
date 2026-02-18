'use client';

import { useState, useCallback, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { visionApi, settingsApi, billingApi } from '@/lib/api';
import { Loader2, Eye, X, Upload, ImageIcon, Copy, Check, Trash2, ChevronDown, ChevronUp, Save, Zap } from 'lucide-react';
import { toast } from 'sonner';
import ImagePickerModal from '@/components/ImagePickerModal';
import { cn } from '@/lib/utils';
import type { PromptPreset, ProviderModel } from '@/types';

const VISION_PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'fal', label: 'fal.ai' },
];

const MODES = [
  { value: 'tag' as const, label: 'Tag' },
  { value: 'describe' as const, label: 'Describe' },
  { value: 'custom' as const, label: 'Custom' },
];

interface SourceImage {
  type: 'gallery' | 'generated' | 'upload';
  id?: number;
  key?: string;
  previewUrl?: string;
  name?: string;
}

function formatDuration(ms: number | undefined | null): string {
  if (!ms) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function VisionPage() {
  const queryClient = useQueryClient();

  // Source image
  const [source, setSource] = useState<SourceImage | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Analysis params
  const [provider, setProvider] = useState('openai');
  const [selectedModel, setSelectedModel] = useState('');
  const [mode, setMode] = useState<'tag' | 'describe' | 'custom'>('describe');
  const [customPrompt, setCustomPrompt] = useState('');

  // Prompt editing
  const [showPrompts, setShowPrompts] = useState(false);
  const [selectedPresetId, setSelectedPresetId] = useState<number | ''>('');
  const [tagPrompt, setTagPrompt] = useState('');
  const [descriptionPrompt, setDescriptionPrompt] = useState('');
  const [promptsModified, setPromptsModified] = useState(false);

  // Results from server
  const [copiedId, setCopiedId] = useState<number | null>(null);

  // Fetch persisted results
  const { data: resultsData, isLoading: resultsLoading } = useQuery({
    queryKey: ['vision-results'],
    queryFn: () => visionApi.listResults(0, 100),
  });

  const results = resultsData?.items ?? [];

  // Fetch models for the selected provider
  const { data: providerModels } = useQuery({
    queryKey: ['provider-models', provider],
    queryFn: () => settingsApi.getProviderModels(provider),
  });

  const visionModels = (providerModels || []).filter(
    (m: ProviderModel) => m.capabilities.includes('vision')
  );

  // Fetch prompt presets
  const { data: presets } = useQuery({
    queryKey: ['presets'],
    queryFn: settingsApi.listPresets,
  });

  // Fetch vision costs
  const { data: visionCosts } = useQuery({
    queryKey: ['vision-costs'],
    queryFn: billingApi.getVisionCosts,
    staleTime: 60_000,
  });

  const currentCost = visionCosts?.costs?.[provider]?.[mode] ?? null;

  // Load active preset prompts on mount
  useEffect(() => {
    if (presets && !promptsModified && selectedPresetId === '') {
      const active = presets.find((p: PromptPreset) => p.is_default);
      if (active) {
        setTagPrompt(active.tag_prompt);
        setDescriptionPrompt(active.description_prompt);
        setSelectedPresetId(active.id);
      }
    }
  }, [presets, promptsModified, selectedPresetId]);

  const handlePresetChange = (presetId: string) => {
    if (presetId === '') {
      setSelectedPresetId('');
      return;
    }
    const id = parseInt(presetId);
    const preset = presets?.find((p: PromptPreset) => p.id === id);
    if (preset) {
      setSelectedPresetId(id);
      setTagPrompt(preset.tag_prompt);
      setDescriptionPrompt(preset.description_prompt);
      setPromptsModified(false);
    }
  };

  // Save prompt changes to the selected preset
  const savePromptMutation = useMutation({
    mutationFn: async () => {
      if (typeof selectedPresetId !== 'number') return;
      const updates: { tag_prompt?: string; description_prompt?: string } = {};
      if (mode === 'tag') updates.tag_prompt = tagPrompt;
      else if (mode === 'describe') updates.description_prompt = descriptionPrompt;
      return settingsApi.updatePreset(selectedPresetId, updates);
    },
    onSuccess: () => {
      setPromptsModified(false);
      queryClient.invalidateQueries({ queryKey: ['presets'] });
      toast.success('Prompt saved to preset');
    },
    onError: (err: Error) => {
      toast.error(`Failed to save: ${err.message}`);
    },
  });

  const handleProviderChange = (newProvider: string) => {
    setProvider(newProvider);
    setSelectedModel('');
  };

  // Analyze mutation
  const analyzeMutation = useMutation({
    mutationFn: visionApi.analyze,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vision-results'] });
    },
    onError: (err: Error) => {
      toast.error(`Analysis failed: ${err.message}`);
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: visionApi.deleteResult,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vision-results'] });
    },
    onError: (err: Error) => {
      toast.error(`Delete failed: ${err.message}`);
    },
  });

  const handleAnalyze = () => {
    if (!source) {
      toast.error('Please select an image');
      return;
    }
    if (mode === 'custom' && !customPrompt.trim()) {
      toast.error('Please enter a custom prompt');
      return;
    }

    const params: Parameters<typeof visionApi.analyze>[0] = {
      provider,
      mode,
    };

    if (selectedModel) params.model = selectedModel;

    if (source.type === 'gallery') params.source_image_id = source.id;
    else if (source.type === 'generated') params.source_generated_id = source.id;
    else if (source.type === 'upload') params.source_upload_key = source.key;

    if (mode === 'custom') {
      params.custom_prompt = customPrompt.trim();
    } else if (mode === 'tag' && tagPrompt.trim()) {
      params.tag_prompt = tagPrompt.trim();
    } else if (mode === 'describe' && descriptionPrompt.trim()) {
      params.description_prompt = descriptionPrompt.trim();
    }

    analyzeMutation.mutate(params);
  };

  const handleFileUpload = useCallback(async (files: FileList | File[]) => {
    const file = Array.from(files)[0];
    if (!file) return;

    if (file.size > 30 * 1024 * 1024) {
      toast.error('File too large (max 30MB)');
      return;
    }

    setUploading(true);
    try {
      const result = await visionApi.uploadSource(file);
      const previewUrl = URL.createObjectURL(file);
      setSource({ type: 'upload', key: result.object_key, previewUrl, name: file.name });
    } catch (err) {
      toast.error(`Upload failed: ${(err as Error).message}`);
    } finally {
      setUploading(false);
    }
  }, []);

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
    if (items.length > 0) {
      const item = items[0];
      setSource({ type: item.type, id: item.id, previewUrl: item.previewUrl });
    }
  };

  const copyToClipboard = async (text: string, id: number) => {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const alreadySelectedIds = source && (source.type === 'gallery' || source.type === 'generated') ? [source.id!] : [];

  // Which prompt is relevant for the current mode
  const showTagPrompt = mode === 'tag';
  const showDescriptionPrompt = mode === 'describe';

  return (
    <div className="max-w-5xl mx-auto space-y-6" onPaste={handlePaste}>
      <div>
        <h1 className="text-2xl font-bold">Vision</h1>
        <p className="text-muted-foreground mt-1">
          Analyze images with AI vision models — tag, describe, or ask custom questions
        </p>
      </div>

      {/* Analysis Form */}
      <section className="bg-card rounded-xl border border-border p-6 space-y-4">
        {/* Source Image */}
        <div>
          <label className="block text-sm font-medium mb-2">Source Image</label>
          <div className="flex items-start gap-3">
            {source ? (
              <div className="relative group w-40 h-40">
                <div className="w-full h-full rounded-lg border border-border overflow-hidden bg-muted/30">
                  {source.previewUrl ? (
                    <img src={source.previewUrl} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <ImageIcon className="h-8 w-8 text-muted-foreground" />
                    </div>
                  )}
                </div>
                <button
                  onClick={() => setSource(null)}
                  className="absolute -top-1.5 -right-1.5 p-0.5 rounded-full bg-red-500 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
                <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[10px] text-center py-0.5 rounded-b-lg">
                  {source.type === 'gallery' ? `#${source.id}` : source.type === 'generated' ? `Gen #${source.id}` : source.name?.slice(0, 16) || 'Upload'}
                </span>
              </div>
            ) : (
              <>
                <label
                  className="w-40 h-40 rounded-lg border-2 border-dashed border-border hover:border-primary/50 flex flex-col items-center justify-center cursor-pointer transition-colors"
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
                    className="hidden"
                    onChange={(e) => e.target.files && handleFileUpload(e.target.files)}
                  />
                </label>
                <button
                  onClick={() => setPickerOpen(true)}
                  className="w-40 h-40 rounded-lg border-2 border-dashed border-border hover:border-primary/50 flex flex-col items-center justify-center transition-colors"
                >
                  <ImageIcon className="h-5 w-5 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground mt-1">Browse</span>
                </button>
              </>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Drag &amp; drop, paste, upload, or browse gallery/generated images.
          </p>
        </div>

        {/* Controls row */}
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Provider</label>
            <select
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="px-3 py-2 border border-border rounded-lg text-sm"
            >
              {VISION_PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-muted-foreground mb-1">Model</label>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="px-3 py-2 border border-border rounded-lg text-sm min-w-[180px]"
            >
              <option value="">Default</option>
              {visionModels.map((m: ProviderModel) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-muted-foreground mb-1">Mode</label>
            <div className="flex gap-1">
              {MODES.map((m) => (
                <button
                  key={m.value}
                  onClick={() => setMode(m.value)}
                  className={cn(
                    'px-4 py-2 text-sm border rounded-lg transition-colors',
                    mode === m.value
                      ? 'border-primary bg-primary/5 text-primary font-medium'
                      : 'border-border hover:bg-muted'
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleAnalyze}
              disabled={analyzeMutation.isPending || !source || (mode === 'custom' && !customPrompt.trim())}
              className="flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 font-medium"
            >
              {analyzeMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
              Analyze
            </button>
            {currentCost != null && currentCost > 0 && (
              <span className="inline-flex items-center gap-0.5 text-xs text-amber-600 dark:text-amber-400">
                <Zap className="h-3 w-3" />
                ~{currentCost} sparks
              </span>
            )}
          </div>
        </div>

        {/* Custom prompt textarea (custom mode only) */}
        {mode === 'custom' && (
          <div>
            <label className="block text-sm font-medium mb-1">
              Custom Prompt
              <span className="text-muted-foreground font-normal ml-2">
                {customPrompt.length}/4000
              </span>
            </label>
            <textarea
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value.slice(0, 4000))}
              placeholder="Ask anything about this image..."
              className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  handleAnalyze();
                }
              }}
            />
          </div>
        )}

        {/* Prompt configuration (tag & describe modes) */}
        {mode !== 'custom' && (
          <button
            onClick={() => setShowPrompts(!showPrompts)}
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            {showPrompts ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            Prompt Configuration
            {promptsModified && (
              <span className="ml-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                modified
              </span>
            )}
          </button>
        )}

        {mode !== 'custom' && showPrompts && (
          <div className="border border-border rounded-lg p-4 space-y-4">
            {/* Preset selector */}
            <div className="flex items-end gap-3">
              <div className="flex-1 max-w-xs">
                <label className="block text-xs text-muted-foreground mb-1">Prompt Preset</label>
                <select
                  value={selectedPresetId}
                  onChange={(e) => handlePresetChange(e.target.value)}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                >
                  {(presets || []).map((p: PromptPreset) => (
                    <option key={p.id} value={p.id}>
                      {p.name}{p.is_default ? ' (active)' : ''}
                    </option>
                  ))}
                </select>
              </div>
              {promptsModified && (
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      const preset = presets?.find((p: PromptPreset) => p.id === selectedPresetId);
                      if (preset) {
                        setTagPrompt(preset.tag_prompt);
                        setDescriptionPrompt(preset.description_prompt);
                        setPromptsModified(false);
                      }
                    }}
                    className="px-3 py-2 text-xs text-muted-foreground hover:text-foreground border border-border rounded-lg transition-colors"
                  >
                    Reset
                  </button>
                  <button
                    onClick={() => savePromptMutation.mutate()}
                    disabled={savePromptMutation.isPending || typeof selectedPresetId !== 'number'}
                    className="flex items-center gap-1.5 px-3 py-2 text-xs bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 font-medium"
                  >
                    {savePromptMutation.isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Save className="h-3 w-3" />
                    )}
                    Save to Preset
                  </button>
                </div>
              )}
            </div>

            {/* Tag prompt editor */}
            {showTagPrompt && (
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  Tag Prompt Guidance
                  <span className="text-muted-foreground/60 ml-1">(wrapped in system format template)</span>
                </label>
                <textarea
                  value={tagPrompt}
                  onChange={(e) => {
                    setTagPrompt(e.target.value);
                    setPromptsModified(true);
                  }}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[120px] font-mono text-xs leading-relaxed"
                />
              </div>
            )}

            {/* Description prompt editor */}
            {showDescriptionPrompt && (
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  Description Prompt Guidance
                  <span className="text-muted-foreground/60 ml-1">(wrapped in system format template)</span>
                </label>
                <textarea
                  value={descriptionPrompt}
                  onChange={(e) => {
                    setDescriptionPrompt(e.target.value);
                    setPromptsModified(true);
                  }}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[120px] font-mono text-xs leading-relaxed"
                />
              </div>
            )}

            <p className="text-xs text-muted-foreground">
              Edit the prompt guidance above, then click &ldquo;Save to Preset&rdquo; to persist changes to the selected preset.
              Unsaved edits will still be used for the next analysis.
            </p>
          </div>
        )}
      </section>

      {/* Results */}
      {results.length > 0 && (
        <section className="space-y-4">
          <h2 className="font-semibold">
            Results
            <span className="text-muted-foreground font-normal ml-2">({resultsData?.total ?? results.length})</span>
          </h2>

          {results.map((result) => (
            <div
              key={result.id}
              className="bg-card rounded-xl border border-border p-4 space-y-3"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm">
                  <span className={cn(
                    'px-2 py-0.5 rounded-full text-xs font-medium',
                    result.mode === 'tag' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300' :
                    result.mode === 'describe' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' :
                    'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300'
                  )}>
                    {result.mode}
                  </span>
                  <span className="text-muted-foreground">
                    {result.provider} / {result.model}
                  </span>
                  {result.duration_ms != null && (
                    <span className="text-xs text-muted-foreground/70">
                      {formatDuration(result.duration_ms)}
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {new Date(result.created_at).toLocaleTimeString()}
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => {
                      const text = result.result_tags ? result.result_tags.join(', ') : result.result_text || '';
                      copyToClipboard(text, result.id);
                    }}
                    className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors"
                    title="Copy to clipboard"
                  >
                    {copiedId === result.id ? (
                      <Check className="h-3.5 w-3.5 text-green-500" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <button
                    onClick={() => deleteMutation.mutate(result.id)}
                    disabled={deleteMutation.isPending}
                    className="p-1.5 text-muted-foreground hover:text-red-500 hover:bg-muted rounded-md transition-colors"
                    title="Delete result"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {result.mode === 'tag' && result.result_tags && (
                <div className="flex flex-wrap gap-1.5">
                  {result.result_tags.map((tag, i) => (
                    <span
                      key={i}
                      className="px-2.5 py-1 bg-muted rounded-full text-xs font-medium"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}

              {(result.mode === 'describe' || result.mode === 'custom') && result.result_text && (
                <div className="text-sm whitespace-pre-wrap bg-muted/30 rounded-lg p-3 max-h-96 overflow-y-auto">
                  {result.result_text}
                </div>
              )}
            </div>
          ))}
        </section>
      )}

      {/* Empty state */}
      {!resultsLoading && results.length === 0 && (
        <div className="text-center py-16 text-muted-foreground">
          <Eye className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>No analysis results yet</p>
          <p className="text-sm mt-1">Select an image and click Analyze to get started</p>
        </div>
      )}

      {/* Loading state */}
      {resultsLoading && results.length === 0 && (
        <div className="text-center py-16 text-muted-foreground">
          <Loader2 className="h-8 w-8 mx-auto mb-3 animate-spin opacity-30" />
          <p className="text-sm">Loading results...</p>
        </div>
      )}

      <ImagePickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onDone={handlePickerDone}
        alreadySelectedIds={alreadySelectedIds}
        maxSelection={1}
      />
    </div>
  );
}
