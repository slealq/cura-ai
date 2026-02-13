'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { imagesApi, settingsApi, clustersApi } from '@/lib/api';
import { RotateCcw, Plus, Trash2, Check, Copy, Play, HelpCircle, Eye, EyeOff, Shield, ShieldAlert, ShieldCheck, ShieldX, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { getStatusColor, cn } from '@/lib/utils';
import type { APIKeyInfo, ClusteringConfig, GenerationConfig, ProviderConfig, ProviderModel, TrainingConfig, PromptPreset } from '@/types';

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
        <p className="text-sm text-red-600">
          Failed to generate suggestion. Please try again.
        </p>
      )}

      {suggestion && (
        <div className="border border-blue-200 bg-blue-50 rounded-lg p-3 space-y-2">
          <p className="text-xs font-medium text-blue-700">AI Suggestion:</p>
          <div className="text-sm whitespace-pre-wrap bg-white rounded p-2 border border-blue-100 max-h-[200px] overflow-y-auto">
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

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: imagesApi.getStats,
  });

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
        <p className="text-muted-foreground mt-1">
          Pipeline configuration and system status
        </p>
      </div>

      {/* Pipeline Stats */}
      <section className="bg-white rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">Pipeline Statistics</h2>
        {stats ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-4 bg-muted/50 rounded-lg">
              <p className="text-2xl font-bold">{stats.total_images}</p>
              <p className="text-sm text-muted-foreground">Total Images</p>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <p className="text-2xl font-bold">{stats.total_clusters}</p>
              <p className="text-sm text-muted-foreground">Clusters</p>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <p className="text-2xl font-bold">{stats.clustered}</p>
              <p className="text-sm text-muted-foreground">Processed</p>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <p className="text-2xl font-bold text-red-600">{stats.failed}</p>
              <p className="text-sm text-muted-foreground">Failed</p>
            </div>
          </div>
        ) : (
          <p className="text-muted-foreground">Loading stats...</p>
        )}

        {/* Status breakdown */}
        {stats && (
          <div className="mt-4 flex flex-wrap gap-2">
            {[
              { label: 'Pending', count: stats.pending, status: 'pending' },
              { label: 'Ingested', count: stats.ingested, status: 'ingested' },
              { label: 'Tagged', count: stats.tagged, status: 'tagged' },
              { label: 'Described', count: stats.described, status: 'described' },
              { label: 'Embedded', count: stats.embedded, status: 'embedded' },
              { label: 'Clustered', count: stats.clustered, status: 'clustered' },
            ].map((item) => (
              <div
                key={item.label}
                className={cn(
                  'px-3 py-1 rounded-full text-sm',
                  getStatusColor(item.status)
                )}
              >
                {item.label}: {item.count}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Prompt Presets */}
      <section className="bg-white rounded-xl border border-border p-6">
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
                    <span className="shrink-0 ml-2 px-1.5 py-0.5 text-[10px] font-semibold bg-green-100 text-green-700 rounded">
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
                  <textarea
                    value={editTagPrompt}
                    onChange={(e) => setEditTagPrompt(e.target.value)}
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm font-mono resize-y min-h-[180px]"
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
                  <textarea
                    value={editDescPrompt}
                    onChange={(e) => setEditDescPrompt(e.target.value)}
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm font-mono resize-y min-h-[180px]"
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
                      className="flex items-center gap-1.5 px-4 py-2 text-sm border border-green-300 text-green-700 rounded-lg hover:bg-green-50 transition-colors disabled:opacity-50"
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
                      className="flex items-center gap-1.5 px-4 py-2 text-sm border border-red-200 text-red-600 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
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

      {/* API Keys */}
      <APIKeysSettings />

      {/* Provider & Model Selection */}
      <ProviderModelSettings />

      {/* Generation Settings */}
      <GenerationSettings />

      {/* Clustering Settings */}
      <ClusteringSettings />
    </div>
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

  const { data: genConfig, isLoading: genLoading } = useQuery({
    queryKey: ['generation-config'],
    queryFn: settingsApi.getGenerationConfig,
  });

  const { data: trainConfig, isLoading: trainLoading } = useQuery({
    queryKey: ['training-config'],
    queryFn: settingsApi.getTrainingConfig,
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
    mutationFn: (cfg: Partial<GenerationConfig>) => settingsApi.updateGenerationConfig(cfg),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['generation-config'] });
      setGenDraft(data);
      toast.success('Generation settings saved');
    },
    onError: () => toast.error('Failed to save generation settings'),
  });

  const resetGenMutation = useMutation({
    mutationFn: settingsApi.resetGenerationConfig,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['generation-config'] });
      setGenDraft(data);
      toast.success('Generation settings reset');
    },
  });

  const saveTrainMutation = useMutation({
    mutationFn: (cfg: Partial<TrainingConfig>) => settingsApi.updateTrainingConfig(cfg),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['training-config'] });
      setTrainDraft(data);
      toast.success('Training settings saved');
    },
    onError: () => toast.error('Failed to save training settings'),
  });

  const resetTrainMutation = useMutation({
    mutationFn: settingsApi.resetTrainingConfig,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['training-config'] });
      setTrainDraft(data);
      toast.success('Training settings reset');
    },
  });

  if (genLoading || trainLoading || !genDraft || !trainDraft) {
    return (
      <section className="bg-white rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">Generation &amp; Training</h2>
        <p className="text-muted-foreground text-sm">Loading...</p>
      </section>
    );
  }

  return (
    <section className="bg-white rounded-xl border border-border p-6">
      <div className="mb-4">
        <h2 className="font-semibold">Generation &amp; Training</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Default parameters for image generation and LoRA training
        </p>
      </div>

      <div className="space-y-6">
        {/* Generation defaults */}
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3">Generation Defaults</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Base Model</label>
              <select
                value={genDraft.base_model}
                onChange={(e) => setGenDraft({ ...genDraft, base_model: e.target.value })}
                className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
              >
                <option value="flux-dev">Flux.1 Dev</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Width: {genDraft.width}</label>
              <input
                type="range"
                min={256}
                max={2048}
                step={64}
                value={genDraft.width}
                onChange={(e) => setGenDraft({ ...genDraft, width: parseInt(e.target.value) })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Height: {genDraft.height}</label>
              <input
                type="range"
                min={256}
                max={2048}
                step={64}
                value={genDraft.height}
                onChange={(e) => setGenDraft({ ...genDraft, height: parseInt(e.target.value) })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Steps: {genDraft.num_inference_steps}</label>
              <input
                type="range"
                min={1}
                max={50}
                value={genDraft.num_inference_steps}
                onChange={(e) => setGenDraft({ ...genDraft, num_inference_steps: parseInt(e.target.value) })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Guidance: {genDraft.guidance_scale.toFixed(1)}</label>
              <input
                type="range"
                min={0}
                max={200}
                value={Math.round(genDraft.guidance_scale * 10)}
                onChange={(e) => setGenDraft({ ...genDraft, guidance_scale: parseInt(e.target.value) / 10 })}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Default LoRA Scale: {genDraft.default_lora_scale.toFixed(1)}</label>
              <input
                type="range"
                min={0}
                max={20}
                value={Math.round(genDraft.default_lora_scale * 10)}
                onChange={(e) => setGenDraft({ ...genDraft, default_lora_scale: parseInt(e.target.value) / 10 })}
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

        {/* Training defaults */}
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3">Training Defaults</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Steps: {trainDraft.steps}</label>
              <input
                type="range"
                min={100}
                max={4000}
                step={100}
                value={trainDraft.steps}
                onChange={(e) => setTrainDraft({ ...trainDraft, steps: parseInt(e.target.value) })}
                className="w-full"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>100</span>
                <span>4000</span>
              </div>
            </div>
            <div className="flex items-center gap-3 pt-4">
              <button
                onClick={() => setTrainDraft({ ...trainDraft, is_style: !trainDraft.is_style })}
                className={cn(
                  'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors',
                  trainDraft.is_style ? 'bg-primary' : 'bg-gray-300'
                )}
              >
                <span
                  className={cn(
                    'inline-block h-4 w-4 transform rounded-full bg-white transition-transform mt-0.5',
                    trainDraft.is_style ? 'translate-x-4 ml-0.5' : 'translate-x-0.5'
                  )}
                />
              </button>
              <span className="text-sm">Style mode by default</span>
            </div>
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
      <section className="bg-white rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">Clustering</h2>
        <p className="text-muted-foreground text-sm">Loading...</p>
      </section>
    );
  }

  const update = (partial: Partial<ClusteringConfig>) =>
    setDraft((prev) => (prev ? { ...prev, ...partial } : prev));

  return (
    <section className="bg-white rounded-xl border border-border p-6">
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
                draft.use_umap ? 'bg-primary' : 'bg-gray-300'
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
            <p className="text-xs text-amber-600 mb-3">
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
                <input
                  type="range"
                  min={2}
                  max={50}
                  value={draft.umap_n_components}
                  onChange={(e) =>
                    update({ umap_n_components: parseInt(e.target.value) })
                  }
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
                <input
                  type="range"
                  min={2}
                  max={100}
                  value={draft.umap_n_neighbors}
                  onChange={(e) =>
                    update({ umap_n_neighbors: parseInt(e.target.value) })
                  }
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
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={Math.round(draft.umap_min_dist * 100)}
                  onChange={(e) =>
                    update({ umap_min_dist: parseInt(e.target.value) / 100 })
                  }
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
                <input
                  type="range"
                  min={2}
                  max={100}
                  value={draft.hdbscan_min_cluster_size}
                  onChange={(e) =>
                    update({
                      hdbscan_min_cluster_size: parseInt(e.target.value),
                    })
                  }
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
                <input
                  type="range"
                  min={1}
                  max={50}
                  value={draft.hdbscan_min_samples}
                  onChange={(e) =>
                    update({ hdbscan_min_samples: parseInt(e.target.value) })
                  }
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
            <div className="mt-4 p-3 bg-blue-50 rounded-lg text-xs text-blue-800 space-y-1">
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
              <input
                type="range"
                min={2}
                max={200}
                value={draft.kmeans_max_clusters}
                onChange={(e) =>
                  update({ kmeans_max_clusters: parseInt(e.target.value) })
                }
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
      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded-full">
        <ShieldCheck className="h-3 w-3" /> Active
      </span>
    );
  }
  if (status === 'invalid') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-100 text-red-700 rounded-full">
        <ShieldX className="h-3 w-3" /> Invalid
      </span>
    );
  }
  if (status === 'quota_exceeded') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 rounded-full">
        <ShieldAlert className="h-3 w-3" /> Quota Exceeded
      </span>
    );
  }
  if (status === 'not_set') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-500 rounded-full border border-dashed border-gray-300">
        <Shield className="h-3 w-3" /> Not Set
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded-full">
      <Shield className="h-3 w-3" /> Unknown
    </span>
  );
}

function APIKeysSettings() {
  const queryClient = useQueryClient();

  const { data: keys, isLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: settingsApi.getApiKeys,
  });

  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: ({ provider, key }: { provider: string; key: string }) =>
      settingsApi.saveApiKey(provider, key),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
      setEditingProvider(null);
      setKeyInput('');
      setShowKey(false);
      if (data.status === 'active') {
        toast.success(`${PROVIDER_LABELS[data.provider] || data.provider} key saved and validated`);
      } else if (data.status === 'invalid') {
        toast.error(`Key saved but validation failed: ${data.last_error || 'Invalid key'}`);
      } else {
        toast.success(`${PROVIDER_LABELS[data.provider] || data.provider} key saved (status: ${data.status})`);
      }
    },
    onError: () => toast.error('Failed to save API key'),
  });

  const validateMutation = useMutation({
    mutationFn: (provider: string) => settingsApi.validateApiKey(provider),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
      if (data.status === 'active') {
        toast.success(`${PROVIDER_LABELS[data.provider] || data.provider} key is valid`);
      } else {
        toast.error(`Validation result: ${data.status}${data.last_error ? ` - ${data.last_error}` : ''}`);
      }
    },
    onError: () => toast.error('Validation failed'),
  });

  const deleteMutation = useMutation({
    mutationFn: (provider: string) => settingsApi.deleteApiKey(provider),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
      setConfirmDelete(null);
      toast.success('API key removed');
    },
    onError: () => toast.error('Failed to remove key'),
  });

  if (isLoading) {
    return (
      <section className="bg-white rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">API Keys</h2>
        <p className="text-muted-foreground text-sm">Loading...</p>
      </section>
    );
  }

  return (
    <section className="bg-white rounded-xl border border-border p-6">
      <div className="mb-4">
        <h2 className="font-semibold">API Keys</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Manage API keys for AI providers. Keys are encrypted at rest and never exposed after saving.
        </p>
      </div>

      <div className="space-y-3">
        {(keys || []).map((key) => (
          <div
            key={key.provider}
            className="border border-border rounded-lg p-4"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="font-medium text-sm">
                  {PROVIDER_LABELS[key.provider] || key.provider}
                </span>
                <StatusBadge status={key.status} />
              </div>
              <div className="flex items-center gap-2">
                {key.key_suffix && (
                  <span className="text-xs text-muted-foreground font-mono">
                    ...{key.key_suffix}
                  </span>
                )}
                {key.status !== 'not_set' && (
                  <>
                    <button
                      onClick={() => validateMutation.mutate(key.provider)}
                      disabled={validateMutation.isPending}
                      className="px-2.5 py-1 text-xs border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
                    >
                      {validateMutation.isPending && validateMutation.variables === key.provider ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        'Validate'
                      )}
                    </button>
                    {confirmDelete === key.provider ? (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => deleteMutation.mutate(key.provider)}
                          className="px-2.5 py-1 text-xs bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
                        >
                          Confirm
                        </button>
                        <button
                          onClick={() => setConfirmDelete(null)}
                          className="px-2.5 py-1 text-xs border border-border rounded-lg hover:bg-muted transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDelete(key.provider)}
                        className="px-2.5 py-1 text-xs border border-red-200 text-red-600 rounded-lg hover:bg-red-50 transition-colors"
                      >
                        Remove
                      </button>
                    )}
                  </>
                )}
                <button
                  onClick={() => {
                    if (editingProvider === key.provider) {
                      setEditingProvider(null);
                      setKeyInput('');
                      setShowKey(false);
                    } else {
                      setEditingProvider(key.provider);
                      setKeyInput('');
                      setShowKey(false);
                    }
                  }}
                  className="px-2.5 py-1 text-xs border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  {editingProvider === key.provider ? 'Cancel' : key.status === 'not_set' ? 'Add Key' : 'Edit Key'}
                </button>
              </div>
            </div>

            {key.last_validated_at && (
              <p className="text-[10px] text-muted-foreground mt-1">
                Last validated: {new Date(key.last_validated_at).toLocaleString()}
              </p>
            )}

            {editingProvider === key.provider && (
              <div className="mt-3 flex gap-2">
                <div className="relative flex-1">
                  <input
                    type={showKey ? 'text' : 'password'}
                    value={keyInput}
                    onChange={(e) => setKeyInput(e.target.value)}
                    placeholder={`Enter ${PROVIDER_LABELS[key.provider] || key.provider} API key...`}
                    className="w-full px-3 py-1.5 pr-8 border border-border rounded-lg text-sm font-mono"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && keyInput.trim()) {
                        saveMutation.mutate({ provider: key.provider, key: keyInput.trim() });
                      }
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </button>
                </div>
                <button
                  onClick={() => saveMutation.mutate({ provider: key.provider, key: keyInput.trim() })}
                  disabled={saveMutation.isPending || !keyInput.trim()}
                  className="px-4 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Save'}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function ProviderModelSettings() {
  const queryClient = useQueryClient();

  const { data: config, isLoading } = useQuery({
    queryKey: ['provider-config'],
    queryFn: settingsApi.getProviderConfig,
  });

  const [draft, setDraft] = useState<ProviderConfig | null>(null);

  useEffect(() => {
    if (config && !draft) setDraft(config);
  }, [config, draft]);

  // Fetch models for the selected vision provider
  const visionProvider = draft?.vision_provider || 'openai';
  const embeddingProvider = draft?.embedding_provider || 'openai';

  const { data: visionModels } = useQuery({
    queryKey: ['provider-models', visionProvider],
    queryFn: () => settingsApi.getProviderModels(visionProvider),
    enabled: !!draft,
  });

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
      toast.success('Provider settings saved');
    },
    onError: () => toast.error('Failed to save provider settings'),
  });

  const resetMutation = useMutation({
    mutationFn: settingsApi.resetProviderConfig,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['provider-config'] });
      setDraft(data);
      toast.success('Provider settings reset to defaults');
    },
  });

  if (isLoading || !draft) {
    return (
      <section className="bg-white rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">Provider &amp; Model Selection</h2>
        <p className="text-muted-foreground text-sm">Loading...</p>
      </section>
    );
  }

  const visionCapableModels = (visionModels || []).filter((m) =>
    m.capabilities.includes('vision') || m.capabilities.includes('chat')
  );
  const embeddingCapableModels = (embeddingModels || []).filter((m) =>
    m.capabilities.includes('embedding')
  );

  const currentVisionModel = visionProvider === 'openai' ? draft.openai_vision_model : draft.anthropic_vision_model;

  return (
    <section className="bg-white rounded-xl border border-border p-6">
      <div className="mb-4">
        <h2 className="font-semibold">Provider &amp; Model Selection</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Choose which AI providers and models to use for vision (tagging/description) and embeddings.
        </p>
      </div>

      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Vision Provider */}
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Vision Provider</label>
            <select
              value={draft.vision_provider}
              onChange={(e) => setDraft({ ...draft, vision_provider: e.target.value })}
              className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </div>

          {/* Vision Model */}
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Vision Model</label>
            <select
              value={currentVisionModel}
              onChange={(e) => {
                if (draft.vision_provider === 'openai') {
                  setDraft({ ...draft, openai_vision_model: e.target.value });
                } else {
                  setDraft({ ...draft, anthropic_vision_model: e.target.value });
                }
              }}
              className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
            >
              {visionCapableModels.length > 0 ? (
                visionCapableModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))
              ) : (
                <option value={currentVisionModel}>{currentVisionModel}</option>
              )}
            </select>
          </div>

          {/* Embedding Provider */}
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Embedding Provider</label>
            <select
              value={draft.embedding_provider}
              onChange={(e) => setDraft({ ...draft, embedding_provider: e.target.value })}
              className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
            >
              <option value="openai">OpenAI</option>
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
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="flex items-center text-xs text-muted-foreground mb-1">
                Tagging: {draft.max_tokens_tagging}
                <Hint text="Token limit for image tagging responses. Default: 1000." />
              </label>
              <input
                type="range"
                min={100}
                max={4000}
                step={100}
                value={draft.max_tokens_tagging}
                onChange={(e) => setDraft({ ...draft, max_tokens_tagging: parseInt(e.target.value) })}
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
              <input
                type="range"
                min={500}
                max={8000}
                step={100}
                value={draft.max_tokens_description}
                onChange={(e) => setDraft({ ...draft, max_tokens_description: parseInt(e.target.value) })}
                className="w-full"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>500</span>
                <span>8000</span>
              </div>
            </div>
            <div>
              <label className="flex items-center text-xs text-muted-foreground mb-1">
                Summarization: {draft.max_tokens_summarization}
                <Hint text="Token limit for cluster summarization responses. Default: 500." />
              </label>
              <input
                type="range"
                min={100}
                max={2000}
                step={50}
                value={draft.max_tokens_summarization}
                onChange={(e) => setDraft({ ...draft, max_tokens_summarization: parseInt(e.target.value) })}
                className="w-full"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>100</span>
                <span>2000</span>
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
