'use client';

import { useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2, Sparkles, PenLine, Zap, ChevronDown, ChevronUp } from 'lucide-react';
import { toast } from 'sonner';
import { foldersApi, settingsApi, billingApi } from '@/lib/api';
import { cn } from '@/lib/utils';
import ModelSelector from '@/components/ModelSelector';
import { Slider } from '@/components/Slider';
import type { PromptPreset } from '@/types';

interface DescribeAllDialogProps {
  folderId: number;
  imageCount: number;
  onClose: () => void;
  onStarted: (jobId: number, total: number) => void;
}

type Mode = 'manual' | 'auto';
type AutoStep = 'idle' | 'analyzing' | 'questions' | 'generating' | 'done';

const VISION_MODELS = [
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini', provider: 'openai' },
  { value: 'gpt-4o', label: 'GPT-4o', provider: 'openai' },
  { value: 'gpt-5-mini', label: 'GPT-5 Mini', provider: 'openai' },
  { value: 'gpt-5.2', label: 'GPT-5.2', provider: 'openai' },
  { value: 'claude-3-haiku-20240307', label: 'Claude Haiku 3', provider: 'anthropic' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5', provider: 'anthropic' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6', provider: 'anthropic' },
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6', provider: 'anthropic' },
  { value: 'x-ai/grok-4-fast', label: 'Grok 4 Fast', provider: 'fal' },
  { value: 'qwen/qwen3-vl-235b-a22b-instruct', label: 'Qwen3 VL 235B', provider: 'fal' },
  { value: 'google/gemini-2.5-flash', label: 'Gemini 2.5 Flash', provider: 'fal' },
];

export default function DescribeAllDialog({ folderId, imageCount, onClose, onStarted }: DescribeAllDialogProps) {
  const [mode, setMode] = useState<Mode>('manual');
  const [model, setModel] = useState('');
  const [tagPrompt, setTagPrompt] = useState('');
  const [descriptionPrompt, setDescriptionPrompt] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const hasInitialized = useRef(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [temperature, setTemperature] = useState<number>(1.0);
  const [maxTokensTag, setMaxTokensTag] = useState<number>(1000);
  const [maxTokensDescribe, setMaxTokensDescribe] = useState<number>(3000);

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

  // Fetch provider config to derive the configured vision model
  const { data: providerConfig } = useQuery({
    queryKey: ['provider-config'],
    queryFn: settingsApi.getProviderConfig,
  });

  // Fetch vision costs — use folder avg dimensions for accurate estimate
  const { data: visionCosts } = useQuery({
    queryKey: ['vision-costs', 'folder', folderId],
    queryFn: () => billingApi.getVisionCostsEstimate({ folder_id: folderId }),
  });

  // Initialize model and advanced params from provider config
  useEffect(() => {
    if (providerConfig && !hasInitialized.current) {
      hasInitialized.current = true;
      const provider = providerConfig.vision_provider;
      const modelId = provider === 'openai'
        ? providerConfig.openai_vision_model
        : provider === 'anthropic'
          ? providerConfig.anthropic_vision_model
          : providerConfig.fal_vision_model;
      if (VISION_MODELS.some((m) => m.value === modelId)) {
        setModel(modelId);
      } else {
        setModel(VISION_MODELS[0].value);
      }
      setTemperature(providerConfig.vision_temperature ?? 1.0);
      setMaxTokensTag(providerConfig.max_tokens_tagging ?? 1000);
      setMaxTokensDescribe(providerConfig.max_tokens_description ?? 3000);
    }
  }, [providerConfig]);

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

  // Compute cost estimate for selected model (tag + describe + embed)
  const getCostEstimate = (): number | null => {
    if (!visionCosts || !model) return null;
    const selected = VISION_MODELS.find((m) => m.value === model);
    if (!selected?.provider) return null;
    const providerCosts = visionCosts.costs[selected.provider];
    if (!providerCosts) return null;
    const modelCosts = providerCosts[model];
    if (!modelCosts) return null;
    return modelCosts.total || ((modelCosts.tag || 0) + (modelCosts.describe || 0));
  };
  const costPerImage = getCostEstimate();

  const handleSubmit = async () => {
    setSubmitting(true);
    const selectedModel = VISION_MODELS.find((m) => m.value === model);
    try {
      const result = await foldersApi.describe(folderId, {
        provider: selectedModel?.provider || undefined,
        model: model || undefined,
        tag_prompt: tagPrompt || undefined,
        description_prompt: descriptionPrompt || undefined,
        temperature,
        max_tokens_tag: maxTokensTag,
        max_tokens_describe: maxTokensDescribe,
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
              {/* Model */}
              <ModelSelector
                label="Model"
                models={VISION_MODELS}
                value={model}
                onChange={(v) => setModel(v)}
                size="sm"
              />

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

              {/* Advanced Parameters */}
              <button
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                Advanced Parameters
              </button>

              {showAdvanced && (
                <div className="border border-border rounded-lg p-3 space-y-3">
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">
                      Temperature: {temperature.toFixed(1)}
                    </label>
                    <Slider
                      min={0}
                      max={20}
                      value={Math.round(temperature * 10)}
                      onChange={(v) => setTemperature(v / 10)}
                      className="w-full"
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                      <span>0.0</span>
                      <span>2.0</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">
                        Tag Tokens: {maxTokensTag}
                      </label>
                      <Slider
                        min={100}
                        max={4000}
                        step={100}
                        value={maxTokensTag}
                        onChange={(v) => setMaxTokensTag(v)}
                        className="w-full"
                      />
                      <div className="flex justify-between text-[10px] text-muted-foreground">
                        <span>100</span>
                        <span>4000</span>
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">
                        Description Tokens: {maxTokensDescribe}
                      </label>
                      <Slider
                        min={500}
                        max={8000}
                        step={100}
                        value={maxTokensDescribe}
                        onChange={(v) => setMaxTokensDescribe(v)}
                        className="w-full"
                      />
                      <div className="flex justify-between text-[10px] text-muted-foreground">
                        <span>500</span>
                        <span>8000</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

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
          <div className="flex items-center gap-2 justify-end pt-2 border-t border-border">
            {mode === 'manual' && costPerImage !== null && costPerImage > 0 && (
              <span className="inline-flex items-center gap-0.5 text-xs text-amber-600 dark:text-amber-400 mr-auto" title={`~${Math.round(costPerImage)} sparks per image (tag + describe + embed)`}>
                <Zap className="h-3 w-3" />
                ~{Math.round(costPerImage * imageCount)} sparks
                <span className="text-muted-foreground ml-0.5">({Math.round(costPerImage)}/image)</span>
              </span>
            )}
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
