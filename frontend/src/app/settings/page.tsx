'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { settingsApi } from '@/lib/api';
import { RotateCcw, Plus, Trash2, Check, Copy, HelpCircle, Sun, Moon, Monitor } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useTheme } from '@/contexts/ThemeContext';
import ModelSelector from '@/components/ModelSelector';
import type { GenerationConfig, ProviderConfig, TrainingConfig } from '@/types';
import { Slider } from '@/components/Slider';
import { useModelCatalog } from '@/hooks/useModelCatalog';

function PromptSuggest({
  promptType,
  currentPrompt,
  onAccept,
}: {
  promptType: 'description' | 'tag';
  currentPrompt: string;
  onAccept: (suggestion: string) => void;
}) {
  const [changeRequest, setChangeRequest] = useState('');
  const [suggestion, setSuggestion] = useState<string | null>(null);

  const suggestMutation = useMutation({
    mutationFn: () =>
      settingsApi.suggestPrompt({
        current_prompt: currentPrompt,
        change_request: changeRequest,
        prompt_type: promptType,
      }),
    onSuccess: (data) => {
      setSuggestion(data.suggested_prompt);
    },
  });

  const handleAccept = () => {
    if (suggestion) {
      onAccept(suggestion);
      setSuggestion(null);
      setChangeRequest('');
    }
  };

  const handleReject = () => {
    setSuggestion(null);
  };

  return (
    <div className="mt-2 space-y-2">
      <div className="flex gap-2">
        <input
          type="text"
          value={changeRequest}
          onChange={(e) => setChangeRequest(e.target.value)}
          placeholder="Describe how to change the prompt..."
          className="flex-1 px-3 py-1.5 border border-input rounded-lg bg-background text-sm"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && changeRequest.trim()) {
              suggestMutation.mutate();
            }
          }}
        />
        <button
          onClick={() => suggestMutation.mutate()}
          disabled={suggestMutation.isPending || !changeRequest.trim()}
          className="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
        >
          {suggestMutation.isPending ? 'Suggesting...' : 'Suggest'}
        </button>
      </div>

      {suggestMutation.isError && (
        <p className="text-sm text-danger">
          Failed to generate suggestion. Please try again.
        </p>
      )}

      {suggestion && (
        <div className="border border-selection/30 bg-selection-soft rounded-lg p-3 space-y-2">
          <p className="text-xs font-medium text-selection">AI Suggestion:</p>
          <div className="text-sm whitespace-pre-wrap bg-card rounded p-2 border border-selection/20 max-h-[200px] overflow-y-auto">
            {suggestion}
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleAccept}
              className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              Accept
            </button>
            <button
              onClick={handleReject}
              className="px-3 py-1 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
            >
              Reject
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function AutoTextarea({
  value,
  onChange,
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = el.scrollHeight + 'px';
  }, []);

  useEffect(() => { resize(); }, [value, resize]);

  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => { onChange?.(e); resize(); }}
      className={cn('w-full px-4 py-3 border border-input rounded-lg bg-background text-sm leading-relaxed overflow-hidden', className)}
      {...props}
    />
  );
}

type SettingsTab = 'general' | 'prompts' | 'models';

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');

  const { data: presets } = useQuery({
    queryKey: ['presets'],
    queryFn: settingsApi.listPresets,
  });

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [editTagPrompt, setEditTagPrompt] = useState('');
  const [editDescPrompt, setEditDescPrompt] = useState('');

  // Auto-select the active preset on load
  useEffect(() => {
    if (presets && selectedId === null) {
      const active = presets.find((p) => p.is_default);
      if (active) setSelectedId(active.id);
      else if (presets.length > 0) setSelectedId(presets[0].id);
    }
  }, [presets, selectedId]);

  // Populate editor when selection changes
  const selectedPreset = presets?.find((p) => p.id === selectedId);
  useEffect(() => {
    if (selectedPreset) {
      setEditName(selectedPreset.name);
      setEditTagPrompt(selectedPreset.tag_prompt);
      setEditDescPrompt(selectedPreset.description_prompt);
    }
  }, [selectedPreset]);

  const createMutation = useMutation({
    mutationFn: settingsApi.createPreset,
    onSuccess: (preset) => {
      queryClient.invalidateQueries({ queryKey: ['presets'] });
      setSelectedId(preset.id);
      toast.success(`Preset "${preset.name}" created`);
    },
    onError: () => toast.error('Failed to create preset (name may already exist)'),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...rest }: { id: number; name?: string; tag_prompt?: string; description_prompt?: string }) =>
      settingsApi.updatePreset(id, rest),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['presets'] });
      queryClient.invalidateQueries({ queryKey: ['prompt-settings'] });
      toast.success('Preset saved');
    },
    onError: () => toast.error('Failed to save preset'),
  });

  const deleteMutation = useMutation({
    mutationFn: settingsApi.deletePreset,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['presets'] });
      setSelectedId(null);
      toast.success('Preset deleted');
    },
    onError: () => toast.error('Cannot delete the active preset'),
  });

  const activateMutation = useMutation({
    mutationFn: settingsApi.activatePreset,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['presets'] });
      queryClient.invalidateQueries({ queryKey: ['prompt-settings'] });
      toast.success('Preset activated');
    },
  });

  const resetMutation = useMutation({
    mutationFn: () => settingsApi.resetPrompts('all'),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['presets'] });
      queryClient.invalidateQueries({ queryKey: ['prompt-settings'] });
      setEditTagPrompt(data.tag_prompt);
      setEditDescPrompt(data.description_prompt);
      toast.success('Prompts reset to factory defaults');
    },
  });

  const handleSave = () => {
    if (!selectedId) return;
    updateMutation.mutate({
      id: selectedId,
      name: editName,
      tag_prompt: editTagPrompt,
      description_prompt: editDescPrompt,
    });
  };

  const handleNewPreset = () => {
    const name = `Preset ${(presets?.length ?? 0) + 1}`;
    // Use factory defaults from the reset endpoint as a baseline (they're the same text)
    createMutation.mutate({
      name,
      tag_prompt: editTagPrompt || '',
      description_prompt: editDescPrompt || '',
    });
  };

  const handleDuplicate = () => {
    if (!selectedPreset) return;
    createMutation.mutate({
      name: `${selectedPreset.name} (copy)`,
      tag_prompt: selectedPreset.tag_prompt,
      description_prompt: selectedPreset.description_prompt,
    });
  };

  return (
    <div className="mobile-account mx-auto w-full max-w-[880px] space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <div className="flex flex-wrap gap-1 bg-muted rounded-lg p-1 mt-4 w-fit">
          {([
            { key: 'general', label: 'General' },
            { key: 'prompts', label: 'Prompt library' },
            { key: 'models', label: 'Default models' },
          ] as const).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              aria-pressed={activeTab === key}
              className={cn(
                'px-3 py-1 text-sm rounded-md transition-colors',
                activeTab === key ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === 'general' && <AppearanceSettings />}

      {activeTab === 'prompts' && (
      <section className="rounded-lg border border-border bg-background p-4 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div>
            <h2 className="font-semibold">Prompt Library</h2>
            <p className="text-sm text-muted-foreground mt-1">
              Named prompt presets for different image types. The active preset is used by default in the pipeline.
              You control the instructions below; the system automatically adds JSON formatting and error handling.
            </p>
          </div>
          <button
            onClick={handleNewPreset}
            disabled={createMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            New Preset
          </button>
        </div>

        <div className="flex flex-col gap-5 md:flex-row md:min-h-[500px]">
          {/* Left column: preset list */}
          <div className="w-full shrink-0 space-y-2 overflow-y-auto max-h-[240px] md:max-h-[600px] md:w-48 md:pr-2">
            {presets?.map((preset) => (
              <button
                key={preset.id}
                onClick={() => setSelectedId(preset.id)}
                className={cn(
                  'w-full text-left px-3 py-2.5 rounded-lg border transition-colors',
                  selectedId === preset.id
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:bg-muted/50'
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium truncate">{preset.name}</span>
                  {preset.is_default && (
                    <span className="shrink-0 ml-2 px-1.5 py-0.5 text-[10px] font-semibold bg-success/10 text-success rounded">
                      Active
                    </span>
                  )}
                </div>
              </button>
            ))}
            {(!presets || presets.length === 0) && (
              <p className="text-sm text-muted-foreground text-center py-8">No presets yet</p>
            )}
          </div>

          {/* Right column: editor */}
          <div className="flex-1 min-w-0">
            {selectedPreset ? (
              <div className="space-y-4">
                {/* Name */}
                <div>
                  <label className="block text-sm font-medium mb-1">Preset Name</label>
                  <input
                    type="text"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    className="w-full px-3 py-2 border border-input rounded-lg bg-background text-sm"
                  />
                </div>

                {/* Tag prompt */}
                <div>
                  <label className="block text-sm font-medium mb-1">Tag Instructions</label>
                  <AutoTextarea
                    value={editTagPrompt}
                    onChange={(e) => setEditTagPrompt(e.target.value)}
                  />
                  <PromptSuggest
                    promptType="tag"
                    currentPrompt={editTagPrompt}
                    onAccept={setEditTagPrompt}
                  />
                </div>

                {/* Description prompt */}
                <div>
                  <label className="block text-sm font-medium mb-1">Description Instructions</label>
                  <AutoTextarea
                    value={editDescPrompt}
                    onChange={(e) => setEditDescPrompt(e.target.value)}
                  />
                  <PromptSuggest
                    promptType="description"
                    currentPrompt={editDescPrompt}
                    onAccept={setEditDescPrompt}
                  />
                </div>

                {/* Action buttons */}
                <div className="flex items-center gap-2 flex-wrap pt-2">
                  <button
                    onClick={handleSave}
                    disabled={updateMutation.isPending}
                    className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                  >
                    {updateMutation.isPending ? 'Saving...' : 'Save'}
                  </button>

                  {!selectedPreset.is_default && (
                    <button
                      onClick={() => activateMutation.mutate(selectedPreset.id)}
                      disabled={activateMutation.isPending}
                      className="flex items-center gap-1.5 px-4 py-2 text-sm border border-success/30 text-success rounded-lg hover:bg-success/10 transition-colors disabled:opacity-50"
                    >
                      <Check className="h-3.5 w-3.5" />
                      Set as Active
                    </button>
                  )}

                  {selectedPreset.is_default && (
                    <button
                      onClick={() => resetMutation.mutate()}
                      disabled={resetMutation.isPending}
                      className="flex items-center gap-1.5 px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      Reset to Factory
                    </button>
                  )}

                  <button
                    onClick={handleDuplicate}
                    disabled={createMutation.isPending}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
                  >
                    <Copy className="h-3.5 w-3.5" />
                    Duplicate
                  </button>

                  {!selectedPreset.is_default && (
                    <button
                      onClick={() => deleteMutation.mutate(selectedPreset.id)}
                      disabled={deleteMutation.isPending}
                      className="flex items-center gap-1.5 px-4 py-2 text-sm border border-danger/30 text-danger rounded-lg hover:bg-danger/10 transition-colors disabled:opacity-50"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Delete
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                Select a preset to edit
              </div>
            )}
          </div>
        </div>
      </section>
      )}

      {activeTab === 'models' && (
        <div className="space-y-5">
          <VisionModelSettings />
          <LanguageModelSettings />
          <GenerationSettings />
        </div>
      )}

    </div>
  );
}

function getTimezoneList(): string[] {
  try {
    return (Intl as unknown as { supportedValuesOf: (key: string) => string[] }).supportedValuesOf('timeZone');
  } catch {
    return [
      'UTC',
      'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
      'America/Sao_Paulo', 'America/Argentina/Buenos_Aires',
      'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Moscow',
      'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Kolkata', 'Asia/Dubai',
      'Australia/Sydney', 'Pacific/Auckland',
    ];
  }
}

function AppearanceSettings() {
  const { theme, resolvedTheme, setTheme, timezone, setTimezone } = useTheme();
  const timezones = getTimezoneList();
  const browserTz = typeof window !== 'undefined'
    ? Intl.DateTimeFormat().resolvedOptions().timeZone
    : 'UTC';

  const themeOptions = [
    { value: 'light' as const, label: 'Light', icon: Sun },
    { value: 'dark' as const, label: 'Dark', icon: Moon },
    { value: 'auto' as const, label: 'Auto', icon: Monitor },
  ];

  return (
    <section className="rounded-lg border border-border bg-background p-4 sm:p-6">
      <div className="mb-4">
        <h2 className="font-semibold">Appearance</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Theme, timezone, and display preferences
        </p>
      </div>

      <div className="space-y-4">
        {/* Theme Toggle */}
        <div>
          <label className="block text-sm font-medium mb-2">Theme</label>
          <div className="inline-flex rounded-lg border border-border">
            {themeOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setTheme(opt.value)}
                className={cn(
                  'flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors first:rounded-l-lg last:rounded-r-lg',
                  theme === opt.value
                    ? 'bg-primary text-primary-foreground'
                    : 'hover:bg-muted'
                )}
              >
                <opt.icon className="h-4 w-4" />
                {opt.label}
              </button>
            ))}
          </div>
          {theme === 'auto' && (
            <p className="text-xs text-muted-foreground mt-2">
              Currently using <span className="font-medium">{resolvedTheme}</span> mode (light 7 AM - 7 PM in your configured timezone)
            </p>
          )}
        </div>

        {/* Timezone */}
        <div>
          <label className="block text-sm font-medium mb-2">Timezone</label>
          <select
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className="w-full max-w-xs px-3 py-2 border border-input rounded-lg bg-background text-sm bg-card"
          >
            {timezones.map((tz) => (
              <option key={tz} value={tz}>
                {tz.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground mt-1">
            Browser detected: {browserTz.replace(/_/g, ' ')}
          </p>
        </div>
      </div>
    </section>
  );
}

function Hint({ text }: { text: string }) {
  return (
    <span className="relative group inline-flex ml-1 align-middle">
      <HelpCircle className="h-3.5 w-3.5 text-muted-foreground/60 hover:text-muted-foreground cursor-help" />
      <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 rounded-lg bg-gray-900 text-white text-xs leading-relaxed px-3 py-2 opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg">
        {text}
        <span className="absolute top-full left-1/2 -translate-x-1/2 -mt-px border-4 border-transparent border-t-gray-900" />
      </span>
    </span>
  );
}

function GenerationSettings() {
  const queryClient = useQueryClient();
  const { data: catalog, isError: catalogError } = useModelCatalog();
  const BASE_MODELS = (catalog?.generation ?? []).map((m) => ({ value: m.key, label: m.label, hasTraining: m.trainable }));
  const EDIT_MODELS = (catalog?.edit ?? []).map((m) => ({ value: m.key, label: m.label }));

  // Base model state
  const { data: baseModelData, isLoading: baseModelLoading } = useQuery({
    queryKey: ['base-model'],
    queryFn: settingsApi.getBaseModel,
  });
  const baseModel = BASE_MODELS.some((m) => m.value === baseModelData?.base_model) ? baseModelData!.base_model : (catalog?.defaults.generation_model ?? '');

  const setBaseModelMutation = useMutation({
    mutationFn: (model: string) => settingsApi.updateBaseModel(model),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['base-model'] });
      // Reset drafts so they reload from the new model's config
      setGenDraft(null);
      setTrainDraft(null);
    },
  });

  // Edit model state
  const { data: editModelData } = useQuery({
    queryKey: ['edit-model'],
    queryFn: settingsApi.getEditModel,
  });
  const editModel = EDIT_MODELS.some((m) => m.value === editModelData?.edit_model) ? editModelData!.edit_model : (catalog?.defaults.edit_model ?? '');

  const setEditModelMutation = useMutation({
    mutationFn: (model: string) => settingsApi.updateEditModel(model),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['edit-model'] });
      toast.success('Default edit model saved');
    },
  });

  // Fetch configs scoped to current base model
  const { data: genConfig, isLoading: genLoading } = useQuery({
    queryKey: ['generation-config', baseModel],
    queryFn: () => settingsApi.getGenerationConfig(baseModel),
    enabled: !!baseModel && !baseModelLoading,
  });

  const modelHasTraining = BASE_MODELS.find((m) => m.value === baseModel)?.hasTraining ?? false;

  const { data: trainConfig, isLoading: trainLoading } = useQuery({
    queryKey: ['training-config', baseModel],
    queryFn: () => settingsApi.getTrainingConfig(baseModel),
    enabled: !!baseModel && !baseModelLoading && modelHasTraining,
  });

  const [genDraft, setGenDraft] = useState<GenerationConfig | null>(null);
  const [trainDraft, setTrainDraft] = useState<TrainingConfig | null>(null);

  useEffect(() => {
    if (genConfig && !genDraft) setGenDraft(genConfig);
  }, [genConfig, genDraft]);

  useEffect(() => {
    if (trainConfig && !trainDraft) setTrainDraft(trainConfig);
  }, [trainConfig, trainDraft]);

  const saveGenMutation = useMutation({
    mutationFn: (cfg: Partial<GenerationConfig>) => settingsApi.updateGenerationConfig(cfg, baseModel),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['generation-config', baseModel] });
      setGenDraft(data);
      toast.success('Generation settings saved');
    },
    onError: () => toast.error('Failed to save generation settings'),
  });

  const resetGenMutation = useMutation({
    mutationFn: () => settingsApi.resetGenerationConfig(baseModel),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['generation-config', baseModel] });
      setGenDraft(data);
      toast.success('Generation settings reset');
    },
  });

  const saveTrainMutation = useMutation({
    mutationFn: (cfg: Partial<TrainingConfig>) => settingsApi.updateTrainingConfig(cfg, baseModel),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['training-config', baseModel] });
      setTrainDraft(data);
      toast.success('Training settings saved');
    },
    onError: () => toast.error('Failed to save training settings'),
  });

  const resetTrainMutation = useMutation({
    mutationFn: () => settingsApi.resetTrainingConfig(baseModel),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['training-config', baseModel] });
      setTrainDraft(data);
      toast.success('Training settings reset');
    },
  });

  if (!catalog || baseModelLoading || genLoading || !genDraft || (modelHasTraining && (trainLoading || !trainDraft))) {
    return (
      <section className="rounded-lg border border-border bg-background p-4 sm:p-6">
        <h2 className="font-semibold mb-4">Generation &amp; Training</h2>
        <p className="text-muted-foreground text-sm">{catalogError ? "Failed to load model catalog." : "Loading..."}</p>
      </section>
    );
  }

  const generationModel = catalog.generation.find(m => m.key === baseModel);
  const canCustomSize = !!generationModel?.params.image_size?.custom_size;
  const canSteps = !!generationModel?.params.steps_guidance;
  const canLora = !!generationModel?.supports_lora;
  const isFlux = baseModel === 'flux-2';
  const isQwen = baseModel === 'qwen-image-2512';
  const trainStepsMax = isQwen ? 30000 : 4000;

  return (
    <section className="rounded-lg border border-border bg-background p-4 sm:p-6">
      <div className="mb-4">
        <h2 className="font-semibold">Generation &amp; Training</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Default parameters for image generation and LoRA training via fal.ai. Training is available for models that support LoRA fine-tuning.
        </p>
      </div>

      <div className="space-y-6">
        {/* Model selector */}
        <ModelSelector
          label="Model"
          models={BASE_MODELS}
          value={baseModel}
          onChange={(v) => {
            if (v !== baseModel) setBaseModelMutation.mutate(v);
          }}
        />

        {/* Training defaults (shown first, only for models that support training) */}
        {modelHasTraining && trainDraft && (
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3">Training Defaults</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Steps: {trainDraft.steps ?? 0}</label>
              <Slider
                min={100}
                max={trainStepsMax}
                step={100}
                value={trainDraft.steps ?? 1000}
                onChange={(v) => setTrainDraft({ ...trainDraft, steps: v })}
                className="w-full"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>100</span>
                <span>{trainStepsMax}</span>
              </div>
            </div>
            {isQwen && (
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">
                  Learning Rate: {(trainDraft.learning_rate ?? 0.0005).toFixed(4)}
                </label>
                <Slider
                  min={1}
                  max={50}
                  value={Math.round((trainDraft.learning_rate ?? 0.0005) * 10000)}
                  onChange={(v) => setTrainDraft({ ...trainDraft, learning_rate: v / 10000 })}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>0.0001</span>
                  <span>0.005</span>
                </div>
              </div>
            )}
            {isFlux && (
              <div className="flex items-center gap-3 pt-4">
                <button
                  onClick={() => setTrainDraft({ ...trainDraft, is_style: !(trainDraft.is_style ?? false) })}
                  className={cn(
                    'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors',
                    (trainDraft.is_style ?? false) ? 'bg-primary' : 'bg-gray-300 dark:bg-gray-600'
                  )}
                >
                  <span
                    className={cn(
                      'inline-block h-4 w-4 transform rounded-full bg-white transition-transform mt-0.5',
                      (trainDraft.is_style ?? false) ? 'translate-x-4 ml-0.5' : 'translate-x-0.5'
                    )}
                  />
                </button>
                <span className="text-sm">Style mode by default</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2 mt-4">
            <button
              onClick={() => saveTrainMutation.mutate(trainDraft)}
              disabled={saveTrainMutation.isPending}
              className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {saveTrainMutation.isPending ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={() => resetTrainMutation.mutate()}
              disabled={resetTrainMutation.isPending}
              className="flex items-center gap-1.5 px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset
            </button>
          </div>
        </div>
        )}

        {/* Generation defaults (shown second) */}
        {(canCustomSize || canSteps || canLora) && <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3">Generation Defaults</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {canCustomSize && <div>
              <label className="text-xs text-muted-foreground mb-1 block">Width: {genDraft.width}</label>
              <Slider
                min={256}
                max={2048}
                step={64}
                value={genDraft.width}
                onChange={(v) => setGenDraft({ ...genDraft, width: v })}
                className="w-full"
              />
            </div>}
            {canCustomSize && <div>
              <label className="text-xs text-muted-foreground mb-1 block">Height: {genDraft.height}</label>
              <Slider
                min={256}
                max={2048}
                step={64}
                value={genDraft.height}
                onChange={(v) => setGenDraft({ ...genDraft, height: v })}
                className="w-full"
              />
            </div>}
            {canSteps && <div>
              <label className="text-xs text-muted-foreground mb-1 block">Steps: {genDraft.num_inference_steps}</label>
              <Slider
                min={generationModel?.params.steps_guidance?.steps?.minimum ?? 1}
                max={generationModel?.params.steps_guidance?.steps?.maximum ?? 50}
                value={genDraft.num_inference_steps}
                onChange={(v) => setGenDraft({ ...genDraft, num_inference_steps: v })}
                className="w-full"
              />
            </div>}
            {canSteps && <div>
              <label className="text-xs text-muted-foreground mb-1 block">Guidance: {genDraft.guidance_scale.toFixed(1)}</label>
              <Slider
                min={(generationModel?.params.steps_guidance?.guidance?.minimum ?? 0) * 10}
                max={(generationModel?.params.steps_guidance?.guidance?.maximum ?? 20) * 10}
                value={Math.round(genDraft.guidance_scale * 10)}
                onChange={(v) => setGenDraft({ ...genDraft, guidance_scale: v / 10 })}
                className="w-full"
              />
            </div>}
            {canLora && <div>
              <label className="text-xs text-muted-foreground mb-1 block">Default LoRA Scale: {genDraft.default_lora_scale.toFixed(1)}</label>
              <Slider
                min={0}
                max={20}
                value={Math.round(genDraft.default_lora_scale * 10)}
                onChange={(v) => setGenDraft({ ...genDraft, default_lora_scale: v / 10 })}
                className="w-full"
              />
            </div>}
          </div>
          <div className="flex items-center gap-2 mt-4">
            <button
              onClick={() => saveGenMutation.mutate(genDraft)}
              disabled={saveGenMutation.isPending}
              className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {saveGenMutation.isPending ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={() => resetGenMutation.mutate()}
              disabled={resetGenMutation.isPending}
              className="flex items-center gap-1.5 px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset
            </button>
          </div>
        </div>}

        {/* Edit model selector */}
        <div className="border border-border rounded-lg p-4 mt-6">
          <h3 className="text-sm font-medium mb-3">Default Edit Model</h3>
          <p className="text-xs text-muted-foreground mb-3">
            The default model selected for image editing.
          </p>
          <ModelSelector
            models={EDIT_MODELS}
            value={editModel}
            onChange={(v) => {
              if (v !== editModel) setEditModelMutation.mutate(v);
            }}
            size="sm"
          />
        </div>
      </div>
    </section>
  );
}

function VisionModelSettings() {
  const queryClient = useQueryClient();
  const { data: catalog, isError: catalogError } = useModelCatalog();
  const VISION_MODELS = catalog?.language ?? [];

  const { data: config, isLoading } = useQuery({
    queryKey: ['provider-config'],
    queryFn: settingsApi.getProviderConfig,
  });

  const [draft, setDraft] = useState<ProviderConfig | null>(null);

  useEffect(() => {
    if (config && !draft) setDraft(config);
  }, [config, draft]);

  // Fetch embedding models from OpenAI
  const embeddingProvider = draft?.embedding_provider || 'openai';

  const { data: embeddingModels } = useQuery({
    queryKey: ['provider-models', embeddingProvider],
    queryFn: () => settingsApi.getProviderModels(embeddingProvider),
    enabled: !!draft,
  });

  const saveMutation = useMutation({
    mutationFn: (cfg: Partial<ProviderConfig>) => settingsApi.updateProviderConfig(cfg),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['provider-config'] });
      setDraft(data);
      toast.success('Vision settings saved');
    },
    onError: () => toast.error('Failed to save vision settings'),
  });

  const resetMutation = useMutation({
    mutationFn: () => settingsApi.updateProviderConfig({
      vision_provider: 'fal',
      openai_embedding_model: 'text-embedding-3-small',
      fal_vision_model: catalog!.defaults.vision_model,
      max_tokens_tagging: 1000,
      max_tokens_description: 3000,
      vision_temperature: 1.0,
    }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['provider-config'] });
      setDraft(data);
      toast.success('Vision settings reset to defaults');
    },
  });

  if (isLoading || !draft || !catalog) {
    return (
      <section className="rounded-lg border border-border bg-background p-4 sm:p-6">
        <h2 className="font-semibold mb-4">Vision Models</h2>
        <p className="text-muted-foreground text-sm">{catalogError ? "Failed to load model catalog." : "Loading..."}</p>
      </section>
    );
  }

  const embeddingCapableModels = (embeddingModels || []).filter((m) =>
    m.capabilities.includes('embedding')
  );

  const currentVisionModelId = draft.fal_vision_model;
  const handleVisionModelChange = (modelId: string) => setDraft({ ...draft, vision_provider: 'fal', fal_vision_model: modelId });

  return (
    <section className="rounded-lg border border-border bg-background p-4 sm:p-6">
      <div className="mb-4">
        <h2 className="font-semibold">Vision Models</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Models used for image tagging, describing, and embedding. These tasks send images to the AI model.
        </p>
      </div>

      <div className="space-y-4">
        {/* Vision Model */}
        <ModelSelector
          label="Vision Model"
          models={VISION_MODELS.map((m) => ({ value: m.id, label: m.label, provider: m.vendor }))}
          value={currentVisionModelId}
          onChange={(v) => handleVisionModelChange(v)}
        />

        {/* Embedding Model */}
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Embedding Model</label>
          <select
            value={draft.openai_embedding_model}
            onChange={(e) => setDraft({ ...draft, openai_embedding_model: e.target.value })}
            className="w-full px-3 py-1.5 border border-input rounded-lg bg-background text-sm max-w-xs"
          >
            {embeddingCapableModels.length > 0 ? (
              embeddingCapableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))
            ) : (
              <option value={draft.openai_embedding_model}>{draft.openai_embedding_model}</option>
            )}
          </select>
        </div>

        {/* Model Parameters */}
        <div className="border border-border rounded-lg p-4">
          <h3 className="flex items-center text-sm font-medium mb-3">
            Model Parameters
            <Hint text="Control the behavior and output limits of vision AI models." />
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="flex items-center text-xs text-muted-foreground mb-1">
                Temperature: {(draft.vision_temperature ?? 1.0).toFixed(1)}
                <Hint text="Controls randomness. Lower values (0.0) produce more deterministic outputs. Higher values (1.5-2.0) increase creativity. Default: 1.0." />
              </label>
              <Slider
                min={0}
                max={20}
                value={Math.round((draft.vision_temperature ?? 1.0) * 10)}
                onChange={(v) => setDraft({ ...draft, vision_temperature: v / 10 })}
                className="w-full"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>0.0</span>
                <span>2.0</span>
              </div>
            </div>
            <div>
              <label className="flex items-center text-xs text-muted-foreground mb-1">
                Tagging Tokens: {draft.max_tokens_tagging}
                <Hint text="Maximum output tokens for image tagging. Default: 1000." />
              </label>
              <Slider
                min={100}
                max={4000}
                step={100}
                value={draft.max_tokens_tagging}
                onChange={(v) => setDraft({ ...draft, max_tokens_tagging: v })}
                className="w-full"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>100</span>
                <span>4000</span>
              </div>
            </div>
            <div>
              <label className="flex items-center text-xs text-muted-foreground mb-1">
                Description Tokens: {draft.max_tokens_description}
                <Hint text="Maximum output tokens for image description. Default: 3000." />
              </label>
              <Slider
                min={500}
                max={8000}
                step={100}
                value={draft.max_tokens_description}
                onChange={(v) => setDraft({ ...draft, max_tokens_description: v })}
                className="w-full"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>500</span>
                <span>8000</span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 pt-2">
          <button
            onClick={() => saveMutation.mutate(draft)}
            disabled={saveMutation.isPending}
            className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {saveMutation.isPending ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={() => resetMutation.mutate()}
            disabled={resetMutation.isPending}
            className="flex items-center gap-1.5 px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset to Defaults
          </button>
        </div>
      </div>
    </section>
  );
}

function LanguageModelSettings() {
  const queryClient = useQueryClient();
  const { data: catalog, isError: catalogError } = useModelCatalog();
  const LANGUAGE_MODELS = catalog?.language ?? [];

  const { data: config, isLoading } = useQuery({
    queryKey: ['provider-config'],
    queryFn: settingsApi.getProviderConfig,
  });

  const [draft, setDraft] = useState<ProviderConfig | null>(null);

  useEffect(() => {
    if (config && !draft) setDraft(config);
  }, [config, draft]);

  const saveMutation = useMutation({
    mutationFn: (cfg: Partial<ProviderConfig>) => settingsApi.updateProviderConfig(cfg),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['provider-config'] });
      setDraft(data);
      toast.success('Language settings saved');
    },
    onError: () => toast.error('Failed to save language settings'),
  });

  const resetMutation = useMutation({
    mutationFn: () => settingsApi.updateProviderConfig({
      language_provider: 'fal',
      fal_language_model: catalog!.defaults.language_model,
      max_tokens_summarization: 500,
      max_tokens_expansion: 500,
      max_tokens_suggestion: 2000,
    }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['provider-config'] });
      setDraft(data);
      toast.success('Language settings reset to defaults');
    },
  });

  if (isLoading || !draft || !catalog) {
    return (
      <section className="rounded-lg border border-border bg-background p-4 sm:p-6">
        <h2 className="font-semibold mb-4">Language Models</h2>
        <p className="text-muted-foreground text-sm">{catalogError ? "Failed to load model catalog." : "Loading..."}</p>
      </section>
    );
  }

  const currentLanguageModelId = draft.fal_language_model;
  const handleLanguageModelChange = (modelId: string) => setDraft({ ...draft, language_provider: 'fal', fal_language_model: modelId });

  return (
    <section className="rounded-lg border border-border bg-background p-4 sm:p-6">
      <div className="mb-4">
        <h2 className="font-semibold">Language Models</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Models used for text-only tasks: cluster summarization, prompt expansion, and prompt library suggestions.
        </p>
      </div>

      <div className="space-y-4">
        <ModelSelector
          label="Language Model"
          models={LANGUAGE_MODELS.map((m) => ({ value: m.id, label: m.label, provider: m.vendor }))}
          value={currentLanguageModelId}
          onChange={(v) => handleLanguageModelChange(v)}
        />

        {/* Token Limits */}
        <div className="border border-border rounded-lg p-4">
          <h3 className="flex items-center text-sm font-medium mb-3">
            Token Limits
            <Hint text="Maximum number of output tokens the AI model can generate for each operation. Increase if responses are being cut off; decrease to save costs." />
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="flex items-center text-xs text-muted-foreground mb-1">
                Summarization: {draft.max_tokens_summarization}
                <Hint text="Token limit for cluster summarization responses. Default: 500." />
              </label>
              <Slider
                min={100}
                max={2000}
                step={50}
                value={draft.max_tokens_summarization}
                onChange={(v) => setDraft({ ...draft, max_tokens_summarization: v })}
                className="w-full"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>100</span>
                <span>2000</span>
              </div>
            </div>
            <div>
              <label className="flex items-center text-xs text-muted-foreground mb-1">
                Expansion: {draft.max_tokens_expansion}
                <Hint text="Token limit for prompt expansion (Generate page). Default: 500." />
              </label>
              <Slider
                min={100}
                max={2000}
                step={50}
                value={draft.max_tokens_expansion}
                onChange={(v) => setDraft({ ...draft, max_tokens_expansion: v })}
                className="w-full"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>100</span>
                <span>2000</span>
              </div>
            </div>
            <div>
              <label className="flex items-center text-xs text-muted-foreground mb-1">
                Suggestion: {draft.max_tokens_suggestion}
                <Hint text="Token limit for prompt library AI suggestions. Default: 2000." />
              </label>
              <Slider
                min={500}
                max={4000}
                step={100}
                value={draft.max_tokens_suggestion}
                onChange={(v) => setDraft({ ...draft, max_tokens_suggestion: v })}
                className="w-full"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>500</span>
                <span>4000</span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 pt-2">
          <button
            onClick={() => saveMutation.mutate(draft)}
            disabled={saveMutation.isPending}
            className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {saveMutation.isPending ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={() => resetMutation.mutate()}
            disabled={resetMutation.isPending}
            className="flex items-center gap-1.5 px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset to Defaults
          </button>
        </div>
      </div>
    </section>
  );
}
