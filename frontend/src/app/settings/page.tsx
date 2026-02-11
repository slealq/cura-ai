'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { imagesApi, settingsApi } from '@/lib/api';
import { getStatusColor, cn } from '@/lib/utils';

function GuidanceSuggest({
  guidanceType,
  currentGuidance,
  onAccept,
}: {
  guidanceType: 'description' | 'tag';
  currentGuidance: string;
  onAccept: (suggestion: string) => void;
}) {
  const [changeRequest, setChangeRequest] = useState('');
  const [suggestion, setSuggestion] = useState<string | null>(null);

  const suggestMutation = useMutation({
    mutationFn: () =>
      settingsApi.suggestGuidance({
        current_guidance: currentGuidance,
        change_request: changeRequest,
        guidance_type: guidanceType,
      }),
    onSuccess: (data) => {
      setSuggestion(data.suggested_guidance);
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
          placeholder="Describe how to change the guidance..."
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

  const { data: guidanceSettings } = useQuery({
    queryKey: ['guidance-settings'],
    queryFn: settingsApi.getGuidance,
  });

  const [descriptionGuidance, setDescriptionGuidance] = useState('');
  const [tagGuidance, setTagGuidance] = useState('');

  // Initialize form when data loads
  useEffect(() => {
    if (guidanceSettings) {
      setDescriptionGuidance(guidanceSettings.description_guidance || '');
      setTagGuidance(guidanceSettings.tag_guidance || '');
    }
  }, [guidanceSettings]);

  const updateMutation = useMutation({
    mutationFn: settingsApi.updateGuidance,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['guidance-settings'] });
    },
  });

  const handleSave = () => {
    updateMutation.mutate({
      description_guidance: descriptionGuidance || null,
      tag_guidance: tagGuidance || null,
    });
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8">
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

      {/* Guidance Configuration */}
      <section className="bg-white rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">AI Guidance Configuration</h2>
        <p className="text-sm text-muted-foreground mb-4">
          Set default guidance to influence how images are tagged and described. These settings will be used for all new image processing unless overridden.
        </p>
        <div className="space-y-6">
          <div>
            <label className="block text-sm font-medium mb-2">
              Description Guidance
            </label>
            <textarea
              value={descriptionGuidance}
              onChange={(e) => setDescriptionGuidance(e.target.value)}
              placeholder="e.g., Focus on detailed physical features and positioning for image reproduction"
              className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Guidance text to influence description generation
            </p>
            <GuidanceSuggest
              guidanceType="description"
              currentGuidance={descriptionGuidance}
              onAccept={setDescriptionGuidance}
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              Tag Guidance
            </label>
            <textarea
              value={tagGuidance}
              onChange={(e) => setTagGuidance(e.target.value)}
              placeholder="e.g., Focus on body type, clothing, pose, and setting categorization"
              className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Guidance text to influence tag selection and categorization
            </p>
            <GuidanceSuggest
              guidanceType="tag"
              currentGuidance={tagGuidance}
              onAccept={setTagGuidance}
            />
          </div>

          <button
            onClick={handleSave}
            disabled={updateMutation.isPending}
            className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {updateMutation.isPending ? 'Saving...' : 'Save Settings'}
          </button>
          {updateMutation.isSuccess && (
            <p className="text-sm text-green-600">Settings saved successfully!</p>
          )}
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
