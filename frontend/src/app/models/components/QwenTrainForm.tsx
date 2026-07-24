'use client';

import { useState } from 'react';
import SharedTrainFields, { type SourceType } from './SharedTrainFields';
import { Slider } from '@/components/Slider';
import type { Folder, Cluster } from '@/types';

export interface QwenTrainData {
  name: string;
  trigger_word?: string;
  base_model: 'flux-2' | 'qwen-image-2512';
  folder_id?: number;
  cluster_id?: number;
  steps: number;
  learning_rate: number;
  use_captions: true;
  caption_include_tags: boolean;
  caption_include_description: boolean;
  example_prompts?: string[];
}

interface QwenTrainFormProps {
  baseModel: 'flux-2' | 'qwen-image-2512';
  defaultSteps: number;
  defaultLearningRate: number;
  folders: Folder[];
  clusters: Cluster[];
  isPending: boolean;
  onSubmit: (data: QwenTrainData) => void;
  onCancel: () => void;
}

export default function QwenTrainForm({
  baseModel,
  defaultSteps,
  defaultLearningRate,
  folders,
  clusters,
  isPending,
  onSubmit,
  onCancel,
}: QwenTrainFormProps) {
  const [name, setName] = useState('');
  const [triggerWord, setTriggerWord] = useState('');
  const [samplePromptsText, setSamplePromptsText] = useState('');
  const [sourceType, setSourceType] = useState<SourceType>('folder');
  const [folderId, setFolderId] = useState<number | undefined>(undefined);
  const [clusterId, setClusterId] = useState<number | undefined>(undefined);
  const [steps, setSteps] = useState(defaultSteps);
  const [learningRate, setLearningRate] = useState(defaultLearningRate);
  const [captionTags, setCaptionTags] = useState(true);
  const [captionDescription, setCaptionDescription] = useState(true);

  const hasValidSource = sourceType === 'folder' ? !!folderId : !!clusterId;
  const canSubmit = name.trim() && hasValidSource && (captionTags || captionDescription);

  const handleSubmit = () => {
    if (!canSubmit) return;
    const examplePrompts = samplePromptsText
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean);
    onSubmit({
      name: name.trim(),
      ...(triggerWord.trim() ? { trigger_word: triggerWord.trim() } : {}),
      base_model: baseModel,
      ...(sourceType === 'folder' ? { folder_id: folderId } : { cluster_id: clusterId }),
      steps,
      learning_rate: learningRate,
      use_captions: true,
      caption_include_tags: captionTags,
      caption_include_description: captionDescription,
      ...(examplePrompts.length > 0 ? { example_prompts: examplePrompts } : {}),
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
        <label className="block text-sm font-medium mb-1">Trigger Word (optional)</label>
        <input
          type="text"
          value={triggerWord}
          onChange={(e) => setTriggerWord(e.target.value)}
          placeholder="e.g. TOK"
          className="w-full px-3 py-2 border border-border rounded-lg text-sm"
        />
        <p className="text-xs text-muted-foreground mt-1">
          Caption-based training usually does not need a trigger word
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">
          Training Steps: {steps}
        </label>
        <Slider
          min={100}
          max={30000}
          step={100}
          value={steps}
          onChange={(v) => setSteps(v)}
          className="w-full"
        />
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>100</span>
          <span>30000</span>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">
          Learning Rate: {learningRate.toFixed(4)}
        </label>
        <Slider
          min={1}
          max={50}
          value={Math.round(learningRate * 10000)}
          onChange={(v) => setLearningRate(v / 10000)}
          className="w-full"
        />
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>0.0001</span>
          <span>0.005</span>
        </div>
      </div>

      {/* Captions are always on for caption-based training */}
      <div className="border-t border-border pt-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm font-medium">Per-image captions</span>
          <span className="text-xs text-orange-600 dark:text-orange-400">(required)</span>
        </div>
        <p className="text-xs text-muted-foreground mb-3">
          Include generated tags and descriptions as captions for each training image
        </p>

        <div className="ml-2 space-y-2">
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
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Sample Prompts (optional)</label>
        <textarea
          value={samplePromptsText}
          onChange={(e) => setSamplePromptsText(e.target.value)}
          rows={3}
          placeholder="One prompt per line..."
          className="w-full px-3 py-2 border border-border rounded-lg bg-background text-sm resize-none"
        />
        <p className="text-xs text-muted-foreground mt-1">
          Known prompts that work well with this model. Auto-collected after training if left empty.
        </p>
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
