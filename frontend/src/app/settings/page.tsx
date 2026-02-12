'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { imagesApi, settingsApi } from '@/lib/api';
import { RotateCcw, Plus, Trash2, Check, Copy } from 'lucide-react';
import { toast } from 'sonner';
import { getStatusColor, cn } from '@/lib/utils';
import type { PromptPreset } from '@/types';

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

      {/* Configuration Info */}
      <section className="bg-white rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">Configuration</h2>
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-medium text-muted-foreground">
              AI Providers
            </h3>
            <p className="text-sm mt-1">
              Configure API keys in the backend .env file
            </p>
            <ul className="mt-2 text-sm space-y-1">
              <li>- Vision: OpenAI GPT-4o or Anthropic Claude</li>
              <li>- Embeddings: OpenAI text-embedding-3-small</li>
            </ul>
          </div>

          <div>
            <h3 className="text-sm font-medium text-muted-foreground">
              Clustering
            </h3>
            <p className="text-sm mt-1">
              Default method: HDBSCAN (auto-detect clusters)
            </p>
            <p className="text-sm text-muted-foreground">
              Alternatives: K-means, Graph clustering
            </p>
          </div>

          <div>
            <h3 className="text-sm font-medium text-muted-foreground">
              Storage
            </h3>
            <p className="text-sm mt-1">Local filesystem (./storage)</p>
            <p className="text-sm text-muted-foreground">
              Thumbnails: 200px, 400px, 800px
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
