'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation } from '@tanstack/react-query';
import { generationApi } from '@/lib/api';
import {
  Loader2,
  ArrowLeft,
  FlaskConical,
  ChevronRight,
  CheckCircle,
  XCircle,
  Clock,
} from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import { cn, formatDate } from '@/lib/utils';

const statusBadge: Record<string, { color: string; label: string }> = {
  pending: { color: 'text-gray-500 bg-gray-100 dark:bg-gray-900/50', label: 'Pending' },
  running: { color: 'text-blue-600 bg-blue-100 dark:bg-blue-900/50', label: 'Running' },
  completed: { color: 'text-green-600 bg-green-100 dark:bg-green-900/50', label: 'Completed' },
  failed: { color: 'text-red-600 bg-red-100 dark:bg-red-900/50', label: 'Failed' },
};

function scoreColor(score: number | null): string {
  if (score === null) return 'text-muted-foreground';
  if (score < 4) return 'text-red-600';
  if (score < 7) return 'text-amber-600';
  return 'text-green-600';
}

export default function EvaluatePage() {
  const params = useParams();
  const router = useRouter();
  const loraId = Number(params.id);

  const [sampleCount, setSampleCount] = useState(5);
  const [creativeCount, setCreativeCount] = useState(0);
  const [metricsEnabled, setMetricsEnabled] = useState<string[]>(['embedding_similarity']);
  const [loraScale, setLoraScale] = useState(1.0);
  const [inferenceSteps, setInferenceSteps] = useState(28);
  const [guidanceScale, setGuidanceScale] = useState(3.5);
  const [matchOriginals, setMatchOriginals] = useState(true);
  const [customWidth, setCustomWidth] = useState(1024);
  const [customHeight, setCustomHeight] = useState(1024);
  const [visionProvider, setVisionProvider] = useState<string>('');

  // Fetch LoRA model info
  const { data: lora, isLoading: loraLoading } = useQuery({
    queryKey: ['lora', loraId],
    queryFn: () => generationApi.getLora(loraId),
  });

  // Fetch previous evaluations
  const { data: evalData, isLoading: evalsLoading } = useQuery({
    queryKey: ['evaluations', loraId],
    queryFn: () => generationApi.listEvaluations(loraId),
    refetchInterval: 5000,
  });

  // Start evaluation mutation
  const startMutation = useMutation({
    mutationFn: () =>
      generationApi.startEvaluation(loraId, {
        sample_count: sampleCount,
        creative_count: creativeCount,
        metrics_enabled: metricsEnabled,
        generation_params: {
          lora_scale: loraScale,
          num_inference_steps: inferenceSteps,
          guidance_scale: guidanceScale,
          ...(matchOriginals ? {} : { width: customWidth, height: customHeight }),
        },
        vision_eval_provider: metricsEnabled.includes('vision_eval') && visionProvider
          ? visionProvider
          : undefined,
      }),
    onSuccess: (data) => {
      toast.success('Evaluation started');
      router.push(`/models/${loraId}/evaluations/${data.evaluation_id}`);
    },
    onError: (err: Error) => toast.error(err.message || 'Failed to start evaluation'),
  });

  const toggleMetric = (metric: string) => {
    setMetricsEnabled((prev) =>
      prev.includes(metric) ? prev.filter((m) => m !== metric) : [...prev, metric]
    );
  };

  if (loraLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!lora) {
    return (
      <div className="max-w-4xl mx-auto py-8 text-center text-muted-foreground">
        LoRA model not found
      </div>
    );
  }

  const evaluations = evalData?.items || [];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link
          href="/models"
          className="p-2 hover:bg-muted rounded-lg transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <FlaskConical className="h-6 w-6 text-amber-600" />
            Evaluate: {lora.name}
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Trigger: <code className="bg-muted px-1 py-0.5 rounded">{lora.trigger_word}</code>
            {' · '}{lora.base_model}
            {' · '}{lora.training_images_count} training images
          </p>
        </div>
      </div>

      {/* Configuration Form */}
      <div className="bg-card border border-border rounded-xl p-6 space-y-5">
        <h2 className="text-lg font-semibold">New Evaluation</h2>

        {/* Sample Count */}
        <div>
          <label className="text-sm font-medium">Sample Count</label>
          <div className="flex items-center gap-3 mt-1">
            <input
              type="range"
              min={1}
              max={50}
              value={sampleCount}
              onChange={(e) => setSampleCount(Number(e.target.value))}
              className="flex-1"
            />
            <span className="text-sm font-mono w-8 text-right">{sampleCount}</span>
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Number of training images to sample for comparison
          </p>
        </div>

        {/* Creative Count */}
        <div>
          <label className="text-sm font-medium">Creative Prompts</label>
          <div className="flex items-center gap-3 mt-1">
            <input
              type="range"
              min={0}
              max={20}
              value={creativeCount}
              onChange={(e) => setCreativeCount(Number(e.target.value))}
              className="flex-1"
            />
            <span className="text-sm font-mono w-8 text-right">{creativeCount}</span>
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            AI-generated novel prompts to test model generalization (no reference comparison)
          </p>
        </div>

        {/* Metrics */}
        <div>
          <label className="text-sm font-medium">Metrics</label>
          <div className="flex flex-col gap-2 mt-1">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={metricsEnabled.includes('embedding_similarity')}
                onChange={() => toggleMetric('embedding_similarity')}
                className="rounded"
              />
              Embedding Similarity
              <span className="text-xs text-muted-foreground">(re-describes and compares text embeddings)</span>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={metricsEnabled.includes('vision_eval')}
                onChange={() => toggleMetric('vision_eval')}
                className="rounded"
              />
              Vision AI Evaluation
              <span className="text-xs text-muted-foreground">(sends both images to GPT-4V/Claude for scoring)</span>
            </label>
          </div>
        </div>

        {/* Vision Provider */}
        {metricsEnabled.includes('vision_eval') && (
          <div>
            <label className="text-sm font-medium">Vision Evaluation Provider</label>
            <select
              value={visionProvider}
              onChange={(e) => setVisionProvider(e.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            >
              <option value="">Default (from settings)</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </div>
        )}

        {/* Generation Params */}
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="text-sm font-medium">LoRA Scale</label>
            <input
              type="number"
              step={0.1}
              min={0}
              max={2}
              value={loraScale}
              onChange={(e) => setLoraScale(Number(e.target.value))}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-sm font-medium">Inference Steps</label>
            <input
              type="number"
              min={1}
              max={100}
              value={inferenceSteps}
              onChange={(e) => setInferenceSteps(Number(e.target.value))}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-sm font-medium">Guidance Scale</label>
            <input
              type="number"
              step={0.5}
              min={0}
              max={20}
              value={guidanceScale}
              onChange={(e) => setGuidanceScale(Number(e.target.value))}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
          </div>
        </div>

        {/* Image Size */}
        <div>
          <label className="text-sm font-medium">Image Size</label>
          <div className="flex flex-col gap-2 mt-1">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                checked={matchOriginals}
                onChange={() => setMatchOriginals(true)}
              />
              Match original dimensions
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                checked={!matchOriginals}
                onChange={() => setMatchOriginals(false)}
              />
              Custom size
            </label>
          </div>
          {!matchOriginals && (
            <div className="flex gap-3 mt-2">
              <div>
                <label className="text-xs text-muted-foreground">Width</label>
                <input
                  type="number"
                  min={256}
                  max={2048}
                  step={64}
                  value={customWidth}
                  onChange={(e) => setCustomWidth(Number(e.target.value))}
                  className="w-24 rounded-lg border border-border bg-background px-2 py-1 text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Height</label>
                <input
                  type="number"
                  min={256}
                  max={2048}
                  step={64}
                  value={customHeight}
                  onChange={(e) => setCustomHeight(Number(e.target.value))}
                  className="w-24 rounded-lg border border-border bg-background px-2 py-1 text-sm"
                />
              </div>
            </div>
          )}
        </div>

        {/* Start Button */}
        <button
          onClick={() => startMutation.mutate()}
          disabled={startMutation.isPending || metricsEnabled.length === 0}
          className="flex items-center gap-2 px-5 py-2.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 transition-colors font-medium text-sm disabled:opacity-50"
        >
          {startMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <FlaskConical className="h-4 w-4" />
          )}
          Start Evaluation
        </button>
      </div>

      {/* Previous Evaluations */}
      <div className="bg-card border border-border rounded-xl p-6">
        <h2 className="text-lg font-semibold mb-4">Previous Evaluations</h2>

        {evalsLoading ? (
          <div className="flex items-center justify-center h-20">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : evaluations.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            No evaluations yet. Start one above.
          </p>
        ) : (
          <div className="divide-y divide-border">
            {evaluations.map((ev) => {
              const badge = statusBadge[ev.status] || statusBadge.pending;
              return (
                <Link
                  key={ev.id}
                  href={`/models/${loraId}/evaluations/${ev.id}`}
                  className="flex items-center justify-between py-3 hover:bg-muted/50 -mx-2 px-2 rounded-lg transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className={cn('px-2 py-0.5 rounded-full text-xs font-medium', badge.color)}>
                      {badge.label}
                    </span>
                    <span className="text-sm">{ev.sample_count} samples</span>
                    <span className="text-xs text-muted-foreground">{formatDate(ev.created_at)}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {ev.overall_score !== null && (
                      <span className={cn('text-lg font-bold', scoreColor(ev.overall_score))}>
                        {ev.overall_score.toFixed(1)}
                      </span>
                    )}
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
