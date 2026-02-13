export const PIPELINE_STEPS = [
  { key: 'ingested', label: 'Ingested', color: 'bg-blue-500', description: 'Image uploaded and thumbnails generated' },
  { key: 'tagged', label: 'Tagged', color: 'bg-purple-500', description: 'AI extracted tags and categories' },
  { key: 'described', label: 'Described', color: 'bg-amber-500', description: 'AI generated a detailed description' },
  { key: 'embedded', label: 'Embedded', color: 'bg-emerald-500', description: 'Text embedding created for search and similarity' },
  { key: 'clustered', label: 'Clustered', color: 'bg-rose-500', description: 'Grouped with similar images' },
] as const;

export const STATUS_RANK: Record<string, number> = {
  pending: 0,
  ingested: 1,
  normalized: 2,
  tagged: 3,
  described: 4,
  embedded: 5,
  clustered: 6,
  failed: -1,
};

export function hasReachedStatus(current: string, target: string): boolean {
  const currentRank = STATUS_RANK[current] ?? -1;
  const targetRank = STATUS_RANK[target] ?? -1;
  if (currentRank < 0) return false;
  return currentRank >= targetRank;
}
