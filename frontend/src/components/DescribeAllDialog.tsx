'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2, Sparkles, PenLine } from 'lucide-react';
import { toast } from 'sonner';
import { foldersApi, settingsApi } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { PromptPreset, ProviderModel } from '@/types';

interface DescribeAllDialogProps {
  folderId: number;
  onClose: () => void;
  onStarted: (jobId: number, total: number) => void;
}

type Mode = 'manual' | 'auto';
type AutoStep = 'idle' | 'analyzing' | 'questions' | 'generating' | 'done';

const VISION_PROVIDERS = [
  { value: '', label: 'Default (from settings)' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'fal', label: 'fal.ai' },
];

export default function DescribeAllDialog({ folderId, onClose, onStarted }: DescribeAllDialogProps) {
  const [mode, setMode] = useState<Mode>('manual');
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [tagPrompt, setTagPrompt] = useState('');
  const [descriptionPrompt, setDescriptionPrompt] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Auto mode state
  const [autoStep, setAutoStep] = useState<AutoStep>('idle');
  const [sampleAnalysis, setSampleAnalysis] = useState('');
  const [questions, setQuestions] = useState<string[]>([]);
  const [answers, setAnswers] = useState<string[]>([]);
  const [autoExplanation, setAutoExplanation] = useState('');

  // Load presets
  const { data: presets } = useQuery({
    queryKey: ['presets'],
    queryFn: () => settingsApi.listPresets(),
  });

  // Load models when provider is selected
  const { data: models } = useQuery<ProviderModel[]>({
    queryKey: ['provider-models', provider],
    queryFn: () => settingsApi.getProviderModels(provider),
    enabled: !!provider,
  });

  const visionModels = models?.filter((m) => m.capabilities.includes('vision')) ?? [];

  const handlePresetSelect = (preset: PromptPreset) => {
    setTagPrompt(preset.tag_prompt);
    setDescriptionPrompt(preset.description_prompt);
  };

  const handleAnalyze = async () => {
    setAutoStep('analyzing');
    try {
      const result = await foldersApi.autoPromptQuestions(folderId);
      setSampleAnalysis(result.sample_analysis);
      setQuestions(result.questions);
      setAnswers(new Array(result.questions.length).fill(''));
      setAutoStep('questions');
    } catch (err) {
      toast.error('Failed to analyze images', {
        description: err instanceof Error ? err.message : 'Unknown error',
      });
      setAutoStep('idle');
    }
  };

  const handleGeneratePrompts = async () => {
    setAutoStep('generating');
    try {
      const result = await foldersApi.autoPromptGenerate(folderId, {
        answers: answers.filter((a) => a.trim()),
        sample_analysis: sampleAnalysis,
      });
      setTagPrompt(result.tag_prompt);
      setDescriptionPrompt(result.description_prompt);
      setAutoExplanation(result.explanation);
      setAutoStep('done');
      // Switch to manual mode for review
      setMode('manual');
    } catch (err) {
      toast.error('Failed to generate prompts', {
        description: err instanceof Error ? err.message : 'Unknown error',
      });
      setAutoStep('questions');
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const result = await foldersApi.describe(folderId, {
        provider: provider || undefined,
        model: model || undefined,
        tag_prompt: tagPrompt || undefined,
        description_prompt: descriptionPrompt || undefined,
      });
      onStarted(result.job_id, result.total);
    } catch (err) {
      toast.error('Failed to start describe job', {
        description: err instanceof Error ? err.message : 'Unknown error',
      });
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-50" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="bg-card rounded-xl shadow-xl max-w-lg w-full p-6 space-y-4 max-h-[85vh] overflow-y-auto"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">Describe All Images</h3>
            <div className="flex rounded-lg border border-border overflow-hidden">
              <button
                onClick={() => setMode('manual')}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 text-sm transition-colors',
                  mode === 'manual' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
                )}
              >
                <PenLine className="h-3.5 w-3.5" />
                Manual
              </button>
              <button
                onClick={() => setMode('auto')}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 text-sm transition-colors',
                  mode === 'auto' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
                )}
              >
                <Sparkles className="h-3.5 w-3.5" />
                Auto
              </button>
            </div>
          </div>

          {mode === 'manual' && (
            <div className="space-y-4">
              {/* Provider + Model */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1">Provider</label>
                  <select
                    value={provider}
                    onChange={(e) => { setProvider(e.target.value); setModel(''); }}
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-background"
                  >
                    {VISION_PROVIDERS.map((p) => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1">Model</label>
                  <select
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-background"
                    disabled={!provider}
                  >
                    <option value="">Default</option>
                    {visionModels.map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Preset selector */}
              {presets && presets.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1">Load from Preset</label>
                  <select
                    onChange={(e) => {
                      const preset = presets.find((p) => p.id === Number(e.target.value));
                      if (preset) handlePresetSelect(preset);
                    }}
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-background"
                    defaultValue=""
                  >
                    <option value="">Select a preset...</option>
                    {presets.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}{p.is_default ? ' (active)' : ''}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Tag prompt */}
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">
                  Tag Prompt Guidance
                </label>
                <textarea
                  value={tagPrompt}
                  onChange={(e) => setTagPrompt(e.target.value)}
                  placeholder="Leave empty to use default. Enter custom guidance for how images should be tagged..."
                  rows={3}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-background resize-none"
                />
              </div>

              {/* Description prompt */}
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">
                  Description Prompt Guidance
                </label>
                <textarea
                  value={descriptionPrompt}
                  onChange={(e) => setDescriptionPrompt(e.target.value)}
                  placeholder="Leave empty to use default. Enter custom guidance for how images should be described..."
                  rows={3}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-background resize-none"
                />
              </div>

              {/* Auto-generated explanation */}
              {autoExplanation && (
                <div className="text-xs text-muted-foreground bg-muted/50 rounded-lg p-3">
                  <span className="font-medium">Auto-generated: </span>{autoExplanation}
                </div>
              )}
            </div>
          )}

          {mode === 'auto' && (
            <div className="space-y-4">
              {autoStep === 'idle' && (
                <div className="text-center py-6 space-y-3">
                  <p className="text-sm text-muted-foreground">
                    Analyze sample images from this folder to generate tailored prompts.
                  </p>
                  <button
                    onClick={handleAnalyze}
                    className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm hover:bg-primary/90 transition-colors"
                  >
                    Analyze Images
                  </button>
                </div>
              )}

              {autoStep === 'analyzing' && (
                <div className="flex flex-col items-center py-8 gap-3">
                  <Loader2 className="h-6 w-6 animate-spin text-primary" />
                  <p className="text-sm text-muted-foreground">Analyzing sample images...</p>
                </div>
              )}

              {(autoStep === 'questions' || autoStep === 'generating') && (
                <div className="space-y-4">
                  <div className="bg-muted/50 rounded-lg p-3">
                    <p className="text-xs font-medium text-muted-foreground mb-1">Analysis</p>
                    <p className="text-sm">{sampleAnalysis}</p>
                  </div>

                  <div className="space-y-3">
                    {questions.map((q, i) => (
                      <div key={i}>
                        <label className="block text-sm font-medium mb-1">{q}</label>
                        <input
                          type="text"
                          value={answers[i] || ''}
                          onChange={(e) => {
                            const next = [...answers];
                            next[i] = e.target.value;
                            setAnswers(next);
                          }}
                          className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-background"
                          disabled={autoStep === 'generating'}
                        />
                      </div>
                    ))}
                  </div>

                  <button
                    onClick={handleGeneratePrompts}
                    disabled={autoStep === 'generating' || answers.every((a) => !a.trim())}
                    className={cn(
                      'w-full py-2 rounded-lg text-sm font-medium transition-colors',
                      'bg-primary text-primary-foreground hover:bg-primary/90',
                      'disabled:opacity-50 disabled:cursor-not-allowed',
                      'flex items-center justify-center gap-2'
                    )}
                  >
                    {autoStep === 'generating' ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Generating prompts...
                      </>
                    ) : (
                      'Generate Prompts'
                    )}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Footer */}
          <div className="flex gap-2 justify-end pt-2 border-t border-border">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
            >
              Cancel
            </button>
            {mode === 'manual' && (
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className={cn(
                  'px-4 py-2 text-sm rounded-lg font-medium transition-colors',
                  'bg-primary text-primary-foreground hover:bg-primary/90',
                  'disabled:opacity-50 disabled:cursor-not-allowed',
                  'flex items-center gap-2'
                )}
              >
                {submitting ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Starting...
                  </>
                ) : (
                  'Describe All'
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
