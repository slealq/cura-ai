'use client';

import { useQuery } from '@tanstack/react-query';
import { imagesApi } from '@/lib/api';
import { getStatusColor, cn } from '@/lib/utils';

export default function SettingsPage() {
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: imagesApi.getStats,
  });

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
              <li>• Vision: OpenAI GPT-4o or Anthropic Claude</li>
              <li>• Embeddings: OpenAI text-embedding-3-small</li>
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

      {/* Tag Taxonomy */}
      <section className="bg-white rounded-xl border border-border p-6">
        <h2 className="font-semibold mb-4">Tag Taxonomy</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          {[
            { category: 'Style', examples: 'minimal, editorial, brutalist, organic' },
            { category: 'Subject', examples: 'portrait, product, interior, abstract' },
            { category: 'Medium', examples: 'photo, 3d-render, illustration, vector' },
            { category: 'Mood', examples: 'calm, energetic, premium, dramatic' },
            { category: 'Color Palette', examples: 'warm, cool, neutral, vibrant' },
            { category: 'Lighting', examples: 'natural, studio, soft, dramatic' },
            { category: 'Materials', examples: 'wood, metal, glass, fabric' },
            { category: 'Composition', examples: 'centered, symmetrical, negative-space' },
            { category: 'Typography', examples: 'none, serif, sans-serif, script' },
            { category: 'Era Reference', examples: 'contemporary, retro, mid-century' },
          ].map((item) => (
            <div key={item.category}>
              <p className="font-medium">{item.category}</p>
              <p className="text-muted-foreground text-xs">{item.examples}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
