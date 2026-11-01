'use client';

import LibraryImage from '@/components/LibraryImage';

import { Suspense, useState, useCallback, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { visionApi, settingsApi, billingApi, imagesApi, authUrl } from '@/lib/api';
import { Loader2, X, Copy, Check, Trash2, Save } from 'lucide-react';
import { toast } from 'sonner';
import Stage from '@/components/tools/Stage';
import Composer from '@/components/tools/Composer';
import SourceTray from '@/components/tools/SourceTray';
import Notice from '@/components/tools/Notice';
import { useSearchParams } from 'next/navigation';
import ImagePickerModal from '@/components/ImagePickerModal';
import { cn, formatDateCompact } from '@/lib/utils';
import { Slider } from '@/components/Slider';
import type { PromptPreset } from '@/types';
import { useModelCatalog } from '@/hooks/useModelCatalog';

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
  width?: number;
  height?: number;
}

function formatDuration(ms: number | undefined | null): string {
  if (!ms) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function VisionPage() {
  return (
    <Suspense fallback={<div className="grid h-32 place-items-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>}>
      <VisionPageInner />
    </Suspense>
  );
}

function VisionPageInner() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { data: catalog, isError: catalogError } = useModelCatalog();
  const VISION_MODEL_OPTIONS = catalog?.language ?? [];

  // Source image
  const [sources, setSources] = useState<SourceImage[]>([]);
  const source = sources[0];
  const [pickerOpen, setPickerOpen] = useState(false);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    const ids = (searchParams.get('sources') || '').split(',').map(Number).filter(id => Number.isInteger(id) && id > 0);
    let active = true;
    Promise.all(ids.map(async id => {
      try {
        const image = await imagesApi.get(id);
        const thumbnail = image.thumbnail_uri_medium || image.thumbnail_uri_small;
        return {
          type: 'gallery' as const, id,
          previewUrl: thumbnail ? imagesApi.getThumbnailUrl(thumbnail.split('/').pop()!) : imagesApi.getImageUrl(image.object_key.split('/').pop()!),
          width: image.width ?? undefined, height: image.height ?? undefined,
        };
      } catch {
        toast.error(`Could not load source ${id}`);
        return null;
      }
    })).then(items => {
      if (active) setSources(items.filter((item): item is NonNullable<typeof item> => item !== null));
    });
    return () => { active = false; };
  }, [searchParams]);

  // Analysis params — single model dropdown derives provider
  const [selectedModel, setSelectedModel] = useState('');
  const [mode, setMode] = useState<'tag' | 'describe' | 'custom'>(searchParams.get('mode') === 'custom' ? 'custom' : 'describe');
  const provider = 'fal';
  const [customPrompt, setCustomPrompt] = useState(searchParams.get('prompt') || '');

  // Prompt editing
  const [notice, setNotice] = useState('');
  const [selectedPresetId, setSelectedPresetId] = useState<number | ''>('');
  const [tagPrompt, setTagPrompt] = useState('');
  const [descriptionPrompt, setDescriptionPrompt] = useState('');
  const [promptsModified, setPromptsModified] = useState(false);

  // Advanced parameters
  const [temperature, setTemperature] = useState<number>(1.0);
  const temperatureChanged = useRef(false);
  const uploadUrls = useRef<string[]>([]);
  useEffect(() => () => uploadUrls.current.forEach(url => URL.revokeObjectURL(url)), []);
  const [maxTokens, setMaxTokens] = useState<number>(1000);

  // Results from server
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

  // Fetch persisted results
  const { data: resultsData, isLoading: resultsLoading } = useQuery({
    queryKey: ['vision-results'],
    queryFn: () => visionApi.listResults(0, 100),
  });

  const results = resultsData?.items ?? [];

  // Fetch prompt presets
  const { data: presets } = useQuery({
    queryKey: ['presets'],
    queryFn: settingsApi.listPresets,
  });

  // Fetch provider config for defaults
  const { data: providerConfig } = useQuery({
    queryKey: ['provider-config'],
    queryFn: settingsApi.getProviderConfig,
  });

  // Fetch vision costs — use source image dimensions when available
  const { data: visionCosts } = useQuery({
    queryKey: ['vision-costs', source?.width, source?.height],
    queryFn: () =>
      source?.width && source?.height
        ? billingApi.getVisionCostsEstimate({ width: source.width, height: source.height })
        : billingApi.getVisionCosts(),
    staleTime: 60_000,
  });

  const currentCost = visionCosts?.costs?.[provider]?.[selectedModel]?.[mode] ?? null;

  // Initialize from provider config
  const hasInitConfig = useRef(false);
  useEffect(() => {
    if (providerConfig && catalog && !hasInitConfig.current) {
      hasInitConfig.current = true;
      setTemperature(providerConfig.vision_temperature ?? 1.0);
      // Set max_tokens based on mode default (tag=tagging, describe=description)
      setMaxTokens(mode === 'tag' ? (providerConfig.max_tokens_tagging ?? 1000) : (providerConfig.max_tokens_description ?? 3000));
      // Set model from provider config
      const modelId = providerConfig.fal_vision_model;
      setSelectedModel(catalog.language.some((m) => m.id === modelId) ? modelId : catalog.defaults.vision_model);
    }
  }, [providerConfig, mode, catalog]);

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

  // Analyze mutation
  const analyzeMutation = useMutation({
    mutationFn: async (requests: Parameters<typeof visionApi.analyze>[0][]) => {
      // Each source keeps its own persisted result, including partial successes.
      const results = await Promise.allSettled(requests.map(request => visionApi.analyze(request)));
      if (results.some(result => result.status === 'fulfilled')) {
        queryClient.invalidateQueries({ queryKey: ['vision-results'] });
      }
      const failures = results.filter(result => result.status === 'rejected');
      if (failures.length) throw new Error(`${failures.length} of ${results.length} analyses failed`);
    },
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

    if (mode === 'custom') {
      params.custom_prompt = customPrompt.trim();
    } else if (mode === 'tag' && tagPrompt.trim()) {
      params.tag_prompt = tagPrompt.trim();
    } else if (mode === 'describe' && descriptionPrompt.trim()) {
      params.description_prompt = descriptionPrompt.trim();
    }

    if (catalog?.language.find(entry => entry.id === selectedModel)?.supports_temperature) params.temperature = temperature;
    params.max_tokens = maxTokens;

    analyzeMutation.mutate(sources.map(item => ({
      ...params,
      ...(item.type === 'gallery' ? { source_image_id: item.id } : item.type === 'generated' ? { source_generated_id: item.id } : { source_upload_key: item.key }),
    })));
  };

  const handleFileUpload = useCallback(async (files: FileList | File[]) => {
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        if (file.size > 30 * 1024 * 1024) {
          toast.error(`${file.name}: file too large (max 30MB)`);
          continue;
        }
        try {
          const result = await visionApi.uploadSource(file);
          const previewUrl = URL.createObjectURL(file);
          uploadUrls.current.push(previewUrl);
          setSources(current => [...current, { type: 'upload', key: result.object_key, previewUrl, name: file.name }]);
        } catch (err) {
          toast.error(`Upload failed: ${(err as Error).message}`);
        }
      }
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

  const handlePickerDone = async (items: import('@/components/ImagePickerModal').PickedImage[]) => {
    const additions = await Promise.all(items.map(async item => {
      const sourceData: SourceImage = { type: item.type, id: item.id, previewUrl: item.previewUrl };
      if (item.type === 'gallery') {
        try {
          const image = await imagesApi.get(item.id);
          sourceData.width = image.width ?? undefined;
          sourceData.height = image.height ?? undefined;
        } catch { /* dimensions are optional for cost estimation */ }
      }
      return sourceData;
    }));
    setSources(current => [...current, ...additions.filter(item => !current.some(existing => existing.type === item.type && existing.id === item.id))]);
  };

  const copyToClipboard = async (text: string, id: number) => {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const alreadySelectedIds = sources.filter(item => item.id != null).map(item => item.id!);

  // Which prompt is relevant for the current mode
  const showTagPrompt = mode === 'tag';
  const showDescriptionPrompt = mode === 'describe';

  const activePrompt = mode === 'custom' ? customPrompt : mode === 'tag' ? tagPrompt : descriptionPrompt;
  function updatePrompt(value: string) {
    if (mode === 'custom') setCustomPrompt(value.slice(0, 4000));
    else {
      if (mode === 'tag') setTagPrompt(value);
      else setDescriptionPrompt(value);
      setPromptsModified(true);
    }
  }

  return (
    <div className="-mx-5 -my-5 h-[calc(100%+40px)] min-h-0" onPaste={handlePaste} onDragOver={event => event.preventDefault()} onDrop={handleDrop}>
      <Stage
        canvas={
          <>
            <SourceTray
              sources={sources}
              model="vision"
              limit={Number.MAX_SAFE_INTEGER}
              onChange={setSources}
              onAdd={() => setPickerOpen(true)}
              onUpload={handleFileUpload}
              onUse={label => updatePrompt(`${activePrompt} ${label}`.trim())}
            />
            {analyzeMutation.isPending && <p role="status" className="animate-pulse text-sm text-muted-foreground">Analyzing image…</p>}
            {/* Results */}
            {results.length > 0 && (
              <section className="space-y-4">
                <h2 className="font-semibold">
                  Previous results
                  <span className="text-muted-foreground font-normal ml-2">({resultsData?.total ?? results.length})</span>
                </h2>

                {results.map((result) => (
                  <div
                    key={result.id}
                    className="bg-card rounded-xl border border-border p-4 space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
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
                        {result.cost_sparks != null && (
                          <span className="text-xs text-muted-foreground/70">
                            {result.cost_sparks.toFixed(1)} sparks
                          </span>
                        )}
                        <span className="text-xs text-muted-foreground">
                          {formatDateCompact(result.created_at)}
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

                    <div className="flex gap-3 max-md:flex-col">
                      {result.source_thumbnail_url && (
                        <button
                          onClick={() => setLightboxUrl(authUrl(result.source_full_url || result.source_thumbnail_url!))}
                          className="shrink-0"
                        >
                          <LibraryImage
                            src={authUrl(result.source_thumbnail_url)}
                            alt=""
                            className="h-52 max-w-full rounded object-contain border border-border hover:ring-2 hover:ring-primary/50 transition-shadow cursor-pointer"
                          />
                        </button>
                      )}
                      <div className="min-w-0 flex-1 space-y-3 break-words">
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
                    </div>
                  </div>
                ))}
              </section>
            )}


            {resultsLoading && <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />}
          </>
        }
        composer={
          <Composer
            value={activePrompt}
            onChange={updatePrompt}
            onApply={handleAnalyze}
            disabled={!catalog || !selectedModel || catalogError || uploading || analyzeMutation.isPending || !source || (mode === 'custom' && !customPrompt.trim())}
            model={catalog?.language.find(entry => entry.id === selectedModel)?.label}
            count={sources.length}
            cost={currentCost != null ? currentCost * sources.length : undefined}
            placeholder={mode === 'custom' ? 'Ask anything about this image…' : `${mode === 'tag' ? 'Tag' : 'Description'} prompt guidance…`}
            action="Analyze"
            warning={uploading ? 'Uploading source…' : undefined}
          />
        }
        settings={
          <>
            <h2 className="font-semibold">Vision settings</h2>
            <Notice>{notice}</Notice>
            <label className="grid gap-1">Mode
              <select value={mode} onChange={event => setMode(event.target.value as typeof mode)} className="w-full rounded-md border border-input bg-background p-2">
                {MODES.map(entry => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
              </select>
            </label>
            <label className="grid gap-1">Provider
              <select value={provider} className="w-full rounded-md border border-input bg-background p-2" disabled>
                <option value="fal">fal.ai</option>
              </select>
            </label>
            <label className="grid gap-1">Model
              <select
                value={selectedModel}
                onChange={event => {
                  const value = event.target.value;
                  const previous = catalog?.language.find(entry => entry.id === selectedModel);
                  const next = catalog?.language.find(entry => entry.id === value);
                  setNotice(temperatureChanged.current && previous?.supports_temperature && !next?.supports_temperature ? 'Temperature removed: this model does not support it.' : '');
                  if (previous?.supports_temperature && !next?.supports_temperature) {
                    setTemperature(providerConfig?.vision_temperature ?? 1);
                    temperatureChanged.current = false;
                  }
                  setSelectedModel(value);
                }}
                className="w-full rounded-md border border-input bg-background p-2"
              >
                {VISION_MODEL_OPTIONS.map(entry => <option key={entry.id} value={entry.id}>{entry.label}</option>)}
              </select>
            </label>
            <span className="w-fit rounded-full border border-border px-2 py-0.5 text-xs">Sources: {sources.length}</span>
            {sources.length > 1 && <p className="text-xs text-muted-foreground">Each source is analyzed separately. Estimated cost uses the first source’s dimensions.</p>}
            <h3 className="border-t border-border pt-3 font-medium">Advanced for this model</h3>
            {/* Temperature and Max Tokens */}
            <div className="grid grid-cols-1 gap-4">
              {catalog?.language.find(entry => entry.id === selectedModel)?.supports_temperature && <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  Temperature: {temperature.toFixed(1)}
                </label>
                <Slider
                  min={0}
                  max={20}
                  value={Math.round(temperature * 10)}
                  onChange={(v) => { temperatureChanged.current = true; setTemperature(v / 10); }}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>0.0</span>
                  <span>2.0</span>
                </div>
              </div>}
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  Max Tokens: {maxTokens}
                </label>
                <Slider
                  min={100}
                  max={8000}
                  step={100}
                  value={maxTokens}
                  onChange={(v) => setMaxTokens(v)}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>100</span>
                  <span>8000</span>
                </div>
              </div>
            </div>

            {/* Prompt editing (tag & describe modes only) */}
            {mode !== 'custom' && (
              <>
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
              </>
            )}

          </>
        }
      />
      {/* Lightbox overlay */}
      {lightboxUrl && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 cursor-pointer"
          onClick={() => setLightboxUrl(null)}
        >
          <button
            onClick={() => setLightboxUrl(null)}
            className="absolute top-4 right-4 p-2 text-white/70 hover:text-white transition-colors"
          >
            <X className="h-6 w-6" />
          </button>
          <LibraryImage
            src={lightboxUrl}
            alt=""
            className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}

      <ImagePickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onDone={handlePickerDone}
        alreadySelectedIds={alreadySelectedIds}
        maxSelection={Number.MAX_SAFE_INTEGER}
      />
    </div>
  );
}
