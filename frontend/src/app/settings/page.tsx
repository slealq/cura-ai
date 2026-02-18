'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { settingsApi, clustersApi } from '@/lib/api';
import { RotateCcw, Plus, Trash2, Check, Copy, Play, HelpCircle, Eye, EyeOff, Shield, ShieldAlert, ShieldCheck, ShieldX, Loader2, Sun, Moon, Monitor } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useTheme } from '@/contexts/ThemeContext';
import type { ClusteringConfig, GenerationConfig, ProviderConfig, ProviderModel, TrainingConfig, PromptPreset } from '@/types';
import { Slider } from '@/components/Slider';

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
          className="flex-1 px-3 py-1.5 border border-border rounded-lg text-sm"
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
        <p className="text-sm text-red-600 dark:text-red-400">
          Failed to generate suggestion. Please try again.
        </p>
      )}

      {suggestion && (
        <div className="border border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-900/30 rounded-lg p-3 space-y-2">
          <p className="text-xs font-medium text-blue-700 dark:text-blue-300">AI Suggestion:</p>
          <div className="text-sm whitespace-pre-wrap bg-card rounded p-2 border border-blue-100 dark:border-blue-800 max-h-[200px] overflow-y-auto">
            {suggestion}
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleAccept}
              className="px-3 py-1 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
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
      className={cn('w-full px-4 py-3 border border-border rounded-lg text-sm leading-relaxed overflow-hidden', className)}
      {...props}
    />
  );
}

type SettingsTab = 'appearance' | 'prompts' | 'vision' | 'language' | 'generation' | 'clustering';

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<SettingsTab>('appearance');

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
    <div className="max-w-6xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <div className="flex gap-1 bg-muted rounded-lg p-1 mt-4 w-fit">
          {([
            { key: 'appearance', label: 'Appearance' },
            { key: 'prompts', label: 'Prompt Library' },
            { key: 'vision', label: 'Vision Models' },
            { key: 'language', label: 'Language Models' },
            { key: 'generation', label: 'Generation & Training' },
            { key: 'clustering', label: 'Clustering' },
          ] as const).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
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

      {activeTab === 'appearance' && <AppearanceSettings />}

      {activeTab === 'prompts' && (
      <section className="bg-card rounded-xl border border-border p-6">
        <div className="flex items-center justify-between mb-4">
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

        <div className="flex gap-6 min-h-[500px]">
          {/* Left column: preset list */}
          <div className="w-64 shrink-0 space-y-2 overflow-y-auto max-h-[600px] pr-2">
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
                    <span className="shrink-0 ml-2 px-1.5 py-0.5 text-[10px] font-semibold bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300 rounded">
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
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm"
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
                      className="flex items-center gap-1.5 px-4 py-2 text-sm border border-green-300 text-green-700 dark:border-green-800 dark:text-green-400 rounded-lg hover:bg-green-50 dark:hover:bg-green-900/30 transition-colors disabled:opacity-50"
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
                      className="flex items-center gap-1.5 px-4 py-2 text-sm border border-red-200 text-red-600 dark:border-red-800 dark:text-red-400 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/30 transition-colors disabled:opacity-50"
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

      {activeTab === 'vision' && <VisionModelSettings />}

      {activeTab === 'language' && <LanguageModelSettings />}

      {activeTab === 'generation' && <GenerationSettings />}

      {activeTab === 'clustering' && <ClusteringSettings />}
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
    <section className="bg-card rounded-xl border border-border p-6">
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
            className="w-full max-w-xs px-3 py-2 border border-border rounded-lg text-sm bg-card"
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

const BASE_MODELS = [
  { value: 'nano-banana-pro', label: 'Nano Banana Pro', hasTraining: false },
  { value: 'flux-dev', label: 'Flux', hasTraining: true },
  { value: 'qwen-2.5', label: 'Qwen 2.5', hasTraining: true },
];

function GenerationSettings() {
  const queryClient = useQueryClient();

  // Base model state
  const { data: baseModelData, isLoading: baseModelLoading } = useQuery({
    queryKey: ['base-model'],
    queryFn: settingsApi.getBaseModel,
  });
  const baseModel = baseModelData?.base_model ?? 'flux-dev';

  const setBaseModelMutation = useMutation({
    mutationFn: (model: string) => settingsApi.updateBaseModel(model),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['base-model'] });
      // Reset drafts so they reload from the new model's config
      setGenDraft(null);
      setTrainDraft(null);
    },
  });

  // Fetch configs scoped to current base model
  const { data: genConfig, isLoading: genLoading } = useQuery({
    queryKey: ['generation-config', baseModel],
    queryFn: () => settingsApi.getGenerationConfig(baseModel),
    enabled: !baseModelLoading,
  });

  const modelHasTraining = BASE_MODELS.find((m) => m.value === baseModel)?.hasTraining ?? false;

  const { data: trainConfig, isLoading: trainLoading } = useQuery({
    queryKey: ['training-config', baseModel],
    queryFn: () => settingsApi.getTrainingConfig(baseModel),
    enabled: !baseModelLoading && modelHasTraining,
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

  if (baseModelLoading || genLoading || !genDraft || (modelHasTraining && (trainLoading || !trainDraft))) {
    return (
      <section className="bg-card rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">Generation &amp; Training</h2>
        <p className="text-muted-foreground text-sm">Loading...</p>
      </section>
    );
  }

  const isFlux = baseModel === 'flux-dev';
  const isQwen = baseModel === 'qwen-2.5';
  const trainStepsMax = isQwen ? 30000 : 4000;

  return (
    <section className="bg-card rounded-xl border border-border p-6">
      <div className="mb-4">
        <h2 className="font-semibold">Generation &amp; Training</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Default parameters for image generation and LoRA training via fal.ai. Training is available for models that support LoRA fine-tuning.
        </p>
      </div>

      <div className="space-y-6">
        {/* Provider + Model selector */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Provider</label>
            <select
              className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
              value="fal"
              disabled
            >
              <option value="fal">fal.ai</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Model</label>
            <select
              value={baseModel}
              onChange={(e) => {
                if (e.target.value !== baseModel) {
                  setBaseModelMutation.mutate(e.target.value);
                }
              }}
              disabled={setBaseModelMutation.isPending}
              className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
            >
              {BASE_MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
        </div>

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
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3">Generation Defaults</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Width: {genDraft.width}</label>
              <Slider
                min={256}
                max={2048}
                step={64}
                value={genDraft.width}
                onChange={(v) => setGenDraft({ ...genDraft, width: v })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Height: {genDraft.height}</label>
              <Slider
                min={256}
                max={2048}
                step={64}
                value={genDraft.height}
                onChange={(v) => setGenDraft({ ...genDraft, height: v })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Steps: {genDraft.num_inference_steps}</label>
              <Slider
                min={1}
                max={50}
                value={genDraft.num_inference_steps}
                onChange={(v) => setGenDraft({ ...genDraft, num_inference_steps: v })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Guidance: {genDraft.guidance_scale.toFixed(1)}</label>
              <Slider
                min={0}
                max={200}
                value={Math.round(genDraft.guidance_scale * 10)}
                onChange={(v) => setGenDraft({ ...genDraft, guidance_scale: v / 10 })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Default LoRA Scale: {genDraft.default_lora_scale.toFixed(1)}</label>
              <Slider
                min={0}
                max={20}
                value={Math.round(genDraft.default_lora_scale * 10)}
                onChange={(v) => setGenDraft({ ...genDraft, default_lora_scale: v / 10 })}
                className="w-full"
              />
            </div>
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
        </div>
      </div>
    </section>
  );
}

function ClusteringSettings() {
  const queryClient = useQueryClient();

  const { data: config, isLoading } = useQuery({
    queryKey: ['clustering-config'],
    queryFn: settingsApi.getClusteringConfig,
  });

  const [draft, setDraft] = useState<ClusteringConfig | null>(null);

  useEffect(() => {
    if (config && !draft) {
      setDraft(config);
    }
  }, [config, draft]);

  const saveMutation = useMutation({
    mutationFn: (cfg: Partial<ClusteringConfig>) =>
      settingsApi.updateClusteringConfig(cfg),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['clustering-config'] });
      setDraft(data);
      toast.success('Clustering settings saved');
    },
    onError: () => toast.error('Failed to save clustering settings'),
  });

  const resetMutation = useMutation({
    mutationFn: settingsApi.resetClusteringConfig,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['clustering-config'] });
      setDraft(data);
      toast.success('Clustering settings reset to defaults');
    },
  });

  const reclusterMutation = useMutation({
    mutationFn: async () => {
      if (draft) {
        await settingsApi.updateClusteringConfig(draft);
      }
      return clustersApi.recluster();
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['clustering-config'] });
      queryClient.invalidateQueries({ queryKey: ['clusters'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      toast.success(`Reclustering started (job #${result.job_id})`);
    },
    onError: () => toast.error('Failed to start reclustering'),
  });

  if (isLoading || !draft) {
    return (
      <section className="bg-card rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">Clustering</h2>
        <p className="text-muted-foreground text-sm">Loading...</p>
      </section>
    );
  }

  const update = (partial: Partial<ClusteringConfig>) =>
    setDraft((prev) => (prev ? { ...prev, ...partial } : prev));

  return (
    <section className="bg-card rounded-xl border border-border p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-semibold">Clustering</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Configure dimensionality reduction (UMAP) and clustering algorithm parameters.
          </p>
        </div>
      </div>

      <div className="space-y-6">
        {/* Method selector */}
        <div>
          <label className="flex items-center text-sm font-medium mb-1">
            Method
            <Hint text="HDBSCAN automatically discovers the number of clusters and handles noise well — best for most cases. K-Means forces every image into a cluster and needs you to set a max K. Graph uses community detection on a similarity network." />
          </label>
          <select
            value={draft.method}
            onChange={(e) => update({ method: e.target.value })}
            className="w-48 px-3 py-2 border border-border rounded-lg text-sm"
          >
            <option value="hdbscan">HDBSCAN</option>
            <option value="kmeans">K-Means</option>
            <option value="graph">Graph (Louvain)</option>
          </select>
        </div>

        {/* UMAP section */}
        <div className="border border-border rounded-lg p-4">
          <div className="flex items-center gap-3 mb-1">
            <label className="flex items-center text-sm font-medium">
              UMAP Dimensionality Reduction
              <Hint text="Reduces high-dimensional embeddings (1536 dims) to fewer dimensions before clustering. Strongly recommended — without it, distances become uniform in high dimensions and clustering produces one giant cluster." />
            </label>
            <button
              onClick={() => update({ use_umap: !draft.use_umap })}
              className={cn(
                'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors',
                draft.use_umap ? 'bg-primary' : 'bg-gray-300 dark:bg-gray-600'
              )}
            >
              <span
                className={cn(
                  'inline-block h-4 w-4 transform rounded-full bg-white transition-transform mt-0.5',
                  draft.use_umap ? 'translate-x-4 ml-0.5' : 'translate-x-0.5'
                )}
              />
            </button>
            <span className="text-xs text-muted-foreground">
              {draft.use_umap ? 'Enabled' : 'Disabled'}
            </span>
          </div>
          {!draft.use_umap && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mb-3">
              Disabling UMAP on high-dimensional embeddings often results in poor cluster separation. Only disable if you know your embeddings are already low-dimensional.
            </p>
          )}

          {draft.use_umap && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
              <div>
                <label className="flex items-center text-xs text-muted-foreground mb-1">
                  Components (output dims): {draft.umap_n_components}
                  <Hint text="Number of dimensions after reduction. Lower values (5-10) create tighter, more distinct clusters but may lose nuance. Higher values (15-30) preserve more detail. Start with 10-15 for ~1000 images." />
                </label>
                <Slider
                  min={2}
                  max={50}
                  value={draft.umap_n_components}
                  onChange={(v) => update({ umap_n_components: v })}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>2</span>
                  <span>50</span>
                </div>
              </div>

              <div>
                <label className="flex items-center text-xs text-muted-foreground mb-1">
                  Neighbors: {draft.umap_n_neighbors}
                  <Hint text="How many nearby points UMAP considers when building its graph. Low values (5-10) focus on very local structure, creating many small tight clusters. High values (30-50) capture broader patterns, merging similar groups. For ~900 images, 10-20 is a good range." />
                </label>
                <Slider
                  min={2}
                  max={100}
                  value={draft.umap_n_neighbors}
                  onChange={(v) => update({ umap_n_neighbors: v })}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>2</span>
                  <span>100</span>
                </div>
              </div>

              <div>
                <label className="flex items-center text-xs text-muted-foreground mb-1">
                  Min Distance: {draft.umap_min_dist.toFixed(2)}
                  <Hint text="How tightly UMAP packs points together. 0.0 allows maximum compression, producing dense clumps that are easier to cluster. Higher values (0.3-0.5) spread points out more evenly. For clustering, keep this at or near 0.0." />
                </label>
                <Slider
                  min={0}
                  max={100}
                  value={Math.round(draft.umap_min_dist * 100)}
                  onChange={(v) => update({ umap_min_dist: v / 100 })}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>0.0</span>
                  <span>1.0</span>
                </div>
              </div>

              <div>
                <label className="flex items-center text-xs text-muted-foreground mb-1">
                  Metric
                  <Hint text="Distance metric for comparing embeddings. Cosine measures angle between vectors (ignoring magnitude) — best for text/AI embeddings. Euclidean measures straight-line distance — use if your embeddings are already normalized." />
                </label>
                <select
                  value={draft.umap_metric}
                  onChange={(e) => update({ umap_metric: e.target.value })}
                  className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                >
                  <option value="cosine">Cosine</option>
                  <option value="euclidean">Euclidean</option>
                </select>
              </div>
            </div>
          )}
        </div>

        {/* HDBSCAN params */}
        {draft.method === 'hdbscan' && (
          <div className="border border-border rounded-lg p-4">
            <h3 className="flex items-center text-sm font-medium mb-3">
              HDBSCAN Parameters
              <Hint text="HDBSCAN finds clusters of varying density and automatically determines how many clusters exist. Images that don't fit any cluster are marked as noise/outliers." />
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="flex items-center text-xs text-muted-foreground mb-1">
                  Min Cluster Size: {draft.hdbscan_min_cluster_size}
                  <Hint text="The smallest group of images that can form a cluster. Increase this if you're getting too many tiny clusters. Decrease if meaningful small groups are being treated as noise. For ~900 images, try 10-30." />
                </label>
                <Slider
                  min={2}
                  max={100}
                  value={draft.hdbscan_min_cluster_size}
                  onChange={(v) => update({ hdbscan_min_cluster_size: v })}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>2</span>
                  <span>100</span>
                </div>
              </div>

              <div>
                <label className="flex items-center text-xs text-muted-foreground mb-1">
                  Min Samples: {draft.hdbscan_min_samples}
                  <Hint text="How conservative the clustering is. Higher values require denser neighborhoods to form a cluster, pushing more borderline images into noise. Lower values are more permissive. Try keeping this at or below min_cluster_size." />
                </label>
                <Slider
                  min={1}
                  max={50}
                  value={draft.hdbscan_min_samples}
                  onChange={(v) => update({ hdbscan_min_samples: v })}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>1</span>
                  <span>50</span>
                </div>
              </div>

              <div>
                <label className="flex items-center text-xs text-muted-foreground mb-1">
                  Selection Method
                  <Hint text="How HDBSCAN picks clusters from its hierarchy. EOM (Excess of Mass) favors larger, more stable clusters — good for finding broad themes. Leaf picks the finest-grained clusters at the bottom of the tree — produces more, smaller groups." />
                </label>
                <select
                  value={draft.hdbscan_cluster_selection_method}
                  onChange={(e) =>
                    update({
                      hdbscan_cluster_selection_method: e.target.value,
                    })
                  }
                  className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                >
                  <option value="eom">EOM (Excess of Mass)</option>
                  <option value="leaf">Leaf</option>
                </select>
              </div>
            </div>

            {/* Quick tuning tips */}
            <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/30 rounded-lg text-xs text-blue-800 dark:text-blue-300 space-y-1">
              <p className="font-medium">Quick tuning guide:</p>
              <p>Too many small clusters? Increase min_cluster_size or switch to EOM.</p>
              <p>Everything in one big cluster? Decrease min_cluster_size, lower UMAP components, or try Leaf selection.</p>
              <p>Too many images marked as noise? Lower min_samples or decrease min_cluster_size.</p>
            </div>
          </div>
        )}

        {/* K-Means params */}
        {draft.method === 'kmeans' && (
          <div className="border border-border rounded-lg p-4">
            <h3 className="flex items-center text-sm font-medium mb-3">
              K-Means Parameters
              <Hint text="K-Means partitions all images into exactly K groups. The optimal K is automatically selected using silhouette scoring up to your max. Every image is assigned to a cluster (no noise concept)." />
            </h3>
            <div>
              <label className="flex items-center text-xs text-muted-foreground mb-1">
                Max Clusters: {draft.kmeans_max_clusters}
                <Hint text="Upper bound for automatic K selection. The algorithm tests K=2 up to this value (capped at 20 for speed) and picks the K with the best silhouette score. Set higher if you expect many distinct groups in your collection." />
              </label>
              <Slider
                min={2}
                max={200}
                value={draft.kmeans_max_clusters}
                onChange={(v) => update({ kmeans_max_clusters: v })}
                className="w-full max-w-md"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground max-w-md">
                <span>2</span>
                <span>200</span>
              </div>
            </div>
          </div>
        )}

        {/* Action buttons */}
        <div className="flex items-center gap-2 flex-wrap pt-2">
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

          <button
            onClick={() => reclusterMutation.mutate()}
            disabled={reclusterMutation.isPending}
            className="flex items-center gap-1.5 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            <Play className="h-3.5 w-3.5" />
            {reclusterMutation.isPending ? 'Starting...' : 'Recluster Now'}
          </button>
        </div>
      </div>
    </section>
  );
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  fal: 'fal.ai',
};

function StatusBadge({ status }: { status: string }) {
  if (status === 'active') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300 rounded-full">
        <ShieldCheck className="h-3 w-3" /> Active
      </span>
    );
  }
  if (status === 'invalid') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300 rounded-full">
        <ShieldX className="h-3 w-3" /> Invalid
      </span>
    );
  }
  if (status === 'quota_exceeded') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300 rounded-full">
        <ShieldAlert className="h-3 w-3" /> Quota Exceeded
      </span>
    );
  }
  if (status === 'not_set') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-500 dark:bg-gray-900/50 dark:text-gray-400 rounded-full border border-dashed border-gray-300 dark:border-gray-600">
        <Shield className="h-3 w-3" /> Not Set
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-900/50 dark:text-gray-400 rounded-full">
      <Shield className="h-3 w-3" /> Unknown
    </span>
  );
}

const VISION_MODELS = [
  // OpenAI
  { id: 'gpt-4o-mini', label: 'GPT-4o Mini', provider: 'openai' as const, field: 'openai_vision_model' as const },
  { id: 'gpt-4o', label: 'GPT-4o', provider: 'openai' as const, field: 'openai_vision_model' as const },
  { id: 'gpt-5-mini', label: 'GPT-5 Mini', provider: 'openai' as const, field: 'openai_vision_model' as const },
  { id: 'gpt-5.2', label: 'GPT-5.2', provider: 'openai' as const, field: 'openai_vision_model' as const },
  // Anthropic
  { id: 'claude-3-haiku-20240307', label: 'Claude Haiku 3', provider: 'anthropic' as const, field: 'anthropic_vision_model' as const },
  { id: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5', provider: 'anthropic' as const, field: 'anthropic_vision_model' as const },
  { id: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6', provider: 'anthropic' as const, field: 'anthropic_vision_model' as const },
  { id: 'claude-opus-4-6', label: 'Claude Opus 4.6', provider: 'anthropic' as const, field: 'anthropic_vision_model' as const },
  // fal.ai (OpenRouter)
  { id: 'x-ai/grok-4-fast', label: 'Grok 4 Fast', provider: 'fal' as const, field: 'fal_vision_model' as const },
  { id: 'qwen/qwen3-vl-235b-a22b-instruct', label: 'Qwen3 VL 235B', provider: 'fal' as const, field: 'fal_vision_model' as const },
  { id: 'google/gemini-2.5-flash', label: 'Gemini 2.5 Flash', provider: 'fal' as const, field: 'fal_vision_model' as const },
];

const LANGUAGE_MODELS = [
  // OpenAI
  { id: 'gpt-4o-mini', label: 'GPT-4o Mini', provider: 'openai' as const, field: 'openai_language_model' as const },
  { id: 'gpt-4o', label: 'GPT-4o', provider: 'openai' as const, field: 'openai_language_model' as const },
  { id: 'gpt-5-mini', label: 'GPT-5 Mini', provider: 'openai' as const, field: 'openai_language_model' as const },
  { id: 'gpt-5.2', label: 'GPT-5.2', provider: 'openai' as const, field: 'openai_language_model' as const },
  // Anthropic
  { id: 'claude-3-haiku-20240307', label: 'Claude Haiku 3', provider: 'anthropic' as const, field: 'anthropic_language_model' as const },
  { id: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5', provider: 'anthropic' as const, field: 'anthropic_language_model' as const },
  { id: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6', provider: 'anthropic' as const, field: 'anthropic_language_model' as const },
  { id: 'claude-opus-4-6', label: 'Claude Opus 4.6', provider: 'anthropic' as const, field: 'anthropic_language_model' as const },
  // fal.ai (OpenRouter)
  { id: 'x-ai/grok-4-fast', label: 'Grok 4 Fast', provider: 'fal' as const, field: 'fal_language_model' as const },
  { id: 'qwen/qwen3-vl-235b-a22b-instruct', label: 'Qwen3 VL 235B', provider: 'fal' as const, field: 'fal_language_model' as const },
  { id: 'google/gemini-2.5-flash', label: 'Gemini 2.5 Flash', provider: 'fal' as const, field: 'fal_language_model' as const },
];

function VisionModelSettings() {
  const queryClient = useQueryClient();

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
      vision_provider: 'openai',
      openai_vision_model: 'gpt-4o-mini',
      openai_embedding_model: 'text-embedding-3-small',
      anthropic_vision_model: 'claude-3-haiku-20240307',
      fal_vision_model: 'x-ai/grok-4-fast',
      max_tokens_tagging: 1000,
      max_tokens_description: 3000,
    }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['provider-config'] });
      setDraft(data);
      toast.success('Vision settings reset to defaults');
    },
  });

  if (isLoading || !draft) {
    return (
      <section className="bg-card rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">Vision Models</h2>
        <p className="text-muted-foreground text-sm">Loading...</p>
      </section>
    );
  }

  const embeddingCapableModels = (embeddingModels || []).filter((m) =>
    m.capabilities.includes('embedding')
  );

  // Derive current vision model from provider + per-provider field
  const visionProvider = draft.vision_provider || 'openai';
  const currentVisionModelId = visionProvider === 'openai'
    ? draft.openai_vision_model
    : visionProvider === 'fal'
      ? draft.fal_vision_model
      : draft.anthropic_vision_model;

  const handleVisionModelChange = (modelId: string) => {
    const model = VISION_MODELS.find((m) => m.id === modelId);
    if (!model) return;
    setDraft({
      ...draft,
      vision_provider: model.provider,
      [model.field]: modelId,
    });
  };

  return (
    <section className="bg-card rounded-xl border border-border p-6">
      <div className="mb-4">
        <h2 className="font-semibold">Vision Models</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Models used for image tagging, describing, and embedding. These tasks send images to the AI model.
        </p>
      </div>

      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Vision Model */}
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Vision Model</label>
            <select
              value={currentVisionModelId}
              onChange={(e) => handleVisionModelChange(e.target.value)}
              className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
            >
              {VISION_MODELS.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>

          {/* Embedding Model */}
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Embedding Model</label>
            <select
              value={draft.openai_embedding_model}
              onChange={(e) => setDraft({ ...draft, openai_embedding_model: e.target.value })}
              className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
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
        </div>

        {/* Token Limits */}
        <div className="border border-border rounded-lg p-4">
          <h3 className="flex items-center text-sm font-medium mb-3">
            Token Limits
            <Hint text="Maximum number of output tokens the AI model can generate for each operation. Increase if responses are being cut off; decrease to save costs." />
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="flex items-center text-xs text-muted-foreground mb-1">
                Tagging: {draft.max_tokens_tagging}
                <Hint text="Token limit for image tagging responses. Default: 1000." />
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
                Description: {draft.max_tokens_description}
                <Hint text="Token limit for image description responses. Default: 3000." />
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
      language_provider: 'openai',
      openai_language_model: 'gpt-4o-mini',
      anthropic_language_model: 'claude-3-haiku-20240307',
      fal_language_model: 'x-ai/grok-4-fast',
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

  if (isLoading || !draft) {
    return (
      <section className="bg-card rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">Language Models</h2>
        <p className="text-muted-foreground text-sm">Loading...</p>
      </section>
    );
  }

  // Derive current language model from provider + per-provider field
  const languageProvider = draft.language_provider || 'openai';
  const currentLanguageModelId = languageProvider === 'openai'
    ? draft.openai_language_model
    : languageProvider === 'fal'
      ? draft.fal_language_model
      : draft.anthropic_language_model;

  const handleLanguageModelChange = (modelId: string) => {
    const model = LANGUAGE_MODELS.find((m) => m.id === modelId);
    if (!model) return;
    setDraft({
      ...draft,
      language_provider: model.provider,
      [model.field]: modelId,
    });
  };

  return (
    <section className="bg-card rounded-xl border border-border p-6">
      <div className="mb-4">
        <h2 className="font-semibold">Language Models</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Models used for text-only tasks: cluster summarization, prompt expansion, and prompt library suggestions.
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Language Model</label>
          <select
            value={currentLanguageModelId}
            onChange={(e) => handleLanguageModelChange(e.target.value)}
            className="w-full max-w-md px-3 py-1.5 border border-border rounded-lg text-sm"
          >
            {LANGUAGE_MODELS.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </div>

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
