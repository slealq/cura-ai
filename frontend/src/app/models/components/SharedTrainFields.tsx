'use client';

import { cn } from '@/lib/utils';
import type { Folder, Cluster } from '@/types';

export type SourceType = 'folder' | 'cluster';

interface SharedTrainFieldsProps {
  name: string;
  onNameChange: (v: string) => void;
  sourceType: SourceType;
  onSourceTypeChange: (v: SourceType) => void;
  folderId: number | undefined;
  onFolderIdChange: (v: number | undefined) => void;
  clusterId: number | undefined;
  onClusterIdChange: (v: number | undefined) => void;
  folders: Folder[];
  clusters: Cluster[];
}

export default function SharedTrainFields({
  name,
  onNameChange,
  sourceType,
  onSourceTypeChange,
  folderId,
  onFolderIdChange,
  clusterId,
  onClusterIdChange,
  folders,
  clusters,
}: SharedTrainFieldsProps) {
  return (
    <>
      <div>
        <label className="block text-sm font-medium mb-1">Name *</label>
        <input
          type="text"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="My LoRA Model"
          className="w-full px-3 py-2 border border-border rounded-lg text-sm"
        />
      </div>

      {/* Source Type Toggle */}
      <div>
        <label className="block text-sm font-medium mb-1">Source *</label>
        <div className="flex rounded-lg border border-border overflow-hidden mb-2">
          <button
            onClick={() => {
              onSourceTypeChange('folder');
              onClusterIdChange(undefined);
            }}
            className={cn(
              'flex-1 px-3 py-1.5 text-sm font-medium transition-colors',
              sourceType === 'folder'
                ? 'bg-primary text-primary-foreground'
                : 'hover:bg-muted'
            )}
          >
            Folder
          </button>
          <button
            onClick={() => {
              onSourceTypeChange('cluster');
              onFolderIdChange(undefined);
            }}
            className={cn(
              'flex-1 px-3 py-1.5 text-sm font-medium transition-colors',
              sourceType === 'cluster'
                ? 'bg-primary text-primary-foreground'
                : 'hover:bg-muted'
            )}
          >
            Cluster
          </button>
        </div>

        {sourceType === 'folder' ? (
          <select
            value={folderId ?? ''}
            onChange={(e) => onFolderIdChange(e.target.value ? parseInt(e.target.value) : undefined)}
            className="w-full px-3 py-2 border border-border rounded-lg text-sm"
          >
            <option value="">Select a folder...</option>
            {folders.map((folder) => (
              <option key={folder.id} value={folder.id}>
                {folder.name} ({folder.image_count} images)
              </option>
            ))}
          </select>
        ) : (
          <select
            value={clusterId ?? ''}
            onChange={(e) => onClusterIdChange(e.target.value ? parseInt(e.target.value) : undefined)}
            className="w-full px-3 py-2 border border-border rounded-lg text-sm"
          >
            <option value="">Select a cluster...</option>
            {clusters.map((cluster) => (
              <option key={cluster.id} value={cluster.id}>
                {cluster.display_name || cluster.summary_title || `Cluster ${cluster.id}`} ({cluster.size} images)
              </option>
            ))}
          </select>
        )}
      </div>
    </>
  );
}
