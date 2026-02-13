'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import SharedTrainFields, { type SourceType } from './SharedTrainFields';
import type { Folder, Cluster } from '@/types';

export interface FluxTrainData {
  name: string;
  trigger_word: string;
  base_model: 'flux-dev';
  folder_id?: number;
  cluster_id?: number;
  steps: number;
  is_style: boolean;
  use_captions: boolean;
  caption_include_tags: boolean;
  caption_include_description: boolean;
}

interface FluxTrainFormProps {
  defaultSteps: number;
  defaultIsStyle: boolean;
  folders: Folder[];
  clusters: Cluster[];
  isPending: boolean;
  onSubmit: (data: FluxTrainData) => void;
  onCancel: () => void;
}

export default function FluxTrainForm({
  defaultSteps,
  defaultIsStyle,
  folders,
  clusters,
  isPending,
  onSubmit,
  onCancel,
}: FluxTrainFormProps) {
  const [name, setName] = useState('');
  const [triggerWord, setTriggerWord] = useState('');
  const [sourceType, setSourceType] = useState<SourceType>('folder');
  const [folderId, setFolderId] = useState<number | undefined>(undefined);
  const [clusterId, setClusterId] = useState<number | undefined>(undefined);
  const [steps, setSteps] = useState(defaultSteps);
  const [isStyle, setIsStyle] = useState(defaultIsStyle);
  const [useCaptions, setUseCaptions] = useState(false);
  const [captionTags, setCaptionTags] = useState(true);
  const [captionDescription, setCaptionDescription] = useState(true);

  const hasValidSource = sourceType === 'folder' ? !!folderId : !!clusterId;
  const canSubmit = name.trim() && triggerWord.trim() && hasValidSource && !(useCaptions && !captionTags && !captionDescription);

  const handleSubmit = () => {
    if (!canSubmit) return;
    onSubmit({
      name: name.trim(),
      trigger_word: triggerWord.trim(),
      base_model: 'flux-dev',
      ...(sourceType === 'folder' ? { folder_id: folderId } : { cluster_id: clusterId }),
      steps,
      is_style: isStyle,
      use_captions: useCaptions,
      caption_include_tags: captionTags,
      caption_include_description: captionDescription,
    });
  };

  return (
    <div className="space-y-3">
      <SharedTrainFields
        name={name}
        onNameChange={setName}
        sourceType={sourceType}
        onSourceTypeChange={setSourceType}
        folderId={folderId}
        onFolderIdChange={setFolderId}
        clusterId={clusterId}
        onClusterIdChange={setClusterId}
        folders={folders}
        clusters={clusters}
      />

      <div>
        <label className="block text-sm font-medium mb-1">Trigger Word *</label>
        <input
          type="text"
          value={triggerWord}
          onChange={(e) => setTriggerWord(e.target.value)}
          placeholder="e.g. TOK, MYSTYLE"
          className="w-full px-3 py-2 border border-border rounded-lg text-sm"
        />
        <p className="text-xs text-muted-foreground mt-1">
          Use this word in your prompts to activate the LoRA
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">
          Training Steps: {steps}
        </label>
        <input
          type="range"
          min={100}
          max={4000}
          step={100}
          value={steps}
          onChange={(e) => setSteps(parseInt(e.target.value))}
          className="w-full"
        />
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>100</span>
          <span>4000</span>
        </div>
      </div>

      {/* Style mode */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setIsStyle(!isStyle)}
          className={cn(
            'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors',
            isStyle ? 'bg-primary' : 'bg-gray-300 dark:bg-gray-600'
          )}
        >
          <span
            className={cn(
              'inline-block h-4 w-4 transform rounded-full bg-white transition-transform mt-0.5',
              isStyle ? 'translate-x-4 ml-0.5' : 'translate-x-0.5'
            )}
          />
        </button>
        <span className="text-sm">Style mode</span>
        <span className="text-xs text-muted-foreground">(for artistic styles rather than subjects)</span>
      </div>

      {/* Per-Image Captions */}
      <div className="border-t border-border pt-3">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setUseCaptions(!useCaptions)}
            className={cn(
              'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors',
              useCaptions ? 'bg-primary' : 'bg-gray-300 dark:bg-gray-600'
            )}
          >
            <span
              className={cn(
                'inline-block h-4 w-4 transform rounded-full bg-white transition-transform mt-0.5',
                useCaptions ? 'translate-x-4 ml-0.5' : 'translate-x-0.5'
              )}
            />
          </button>
          <span className="text-sm">Per-image captions</span>
        </div>
        <p className="text-xs text-muted-foreground mt-1.5 ml-12">
          Include generated tags and descriptions as captions for each training image
        </p>

        {useCaptions && (
          <div className="mt-3 ml-12 space-y-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={captionTags}
                onChange={(e) => setCaptionTags(e.target.checked)}
                className="rounded border-gray-300"
              />
              <span className="text-sm">Include tags</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={captionDescription}
                onChange={(e) => setCaptionDescription(e.target.checked)}
                className="rounded border-gray-300"
              />
              <span className="text-sm">Include description</span>
            </label>
            {!captionTags && !captionDescription && (
              <p className="text-xs text-red-500">At least one caption source must be selected</p>
            )}
          </div>
        )}
      </div>

      <div className="flex gap-2 justify-end pt-2">
        <button
          onClick={onCancel}
          className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleSubmit}
          disabled={isPending || !canSubmit}
          className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {isPending ? 'Starting...' : 'Start Training'}
        </button>
      </div>
    </div>
  );
}
