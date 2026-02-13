'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { generationApi, imagesApi } from '@/lib/api';
import {
  Loader2,
  ArrowLeft,
  FlaskConical,
  ChevronDown,
  ChevronUp,
  Trash2,
  XCircle,
  CheckCircle,
  Clock,
  Maximize2,
} from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { cn, formatDate } from '@/lib/utils';
import type { EvaluationPair } from '@/types';

function scoreColor(score: number | null): string {
  if (score === null) return 'text-muted-foreground';
  if (score < 4) return 'text-red-600';
  if (score < 7) return 'text-amber-600';
  return 'text-green-600';
}

function scoreBg(score: number | null): string {
  if (score === null) return 'bg-muted';
  if (score < 4) return 'bg-red-100 dark:bg-red-900/30';
  if (score < 7) return 'bg-amber-100 dark:bg-amber-900/30';
  return 'bg-green-100 dark:bg-green-900/30';
}

function ScoreBar({ label, score, max = 10 }: { label: string; score: number | null; max?: number }) {
  if (score === null) return null;
  const pct = Math.min(100, (score / max) * 100);
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className={cn('font-medium', scoreColor(score))}>{score.toFixed(1)}</span>
      </div>
      <div className="w-full bg-muted rounded-full h-1.5">
        <div
          className={cn(
            'h-1.5 rounded-full transition-all',
            score < 4 ? 'bg-red-500' : score < 7 ? 'bg-amber-500' : 'bg-green-500'
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function PairCard({
  pair,
  evalId,
}: {
  pair: EvaluationPair;
  evalId: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);

  const originalThumb = pair.original_thumbnail
    ? imagesApi.getThumbnailUrl(pair.original_thumbnail.split('/').pop()!)
    : null;
  const originalFullUrl = pair.original_object_key
    ? imagesApi.getImageUrl(pair.original_object_key)
    : null;
  const generatedThumb = pair.generated_thumbnail_medium
    ? generationApi.getThumbnailUrl(pair.generated_thumbnail_medium.split('/').pop()!)
    : null;

  const pairStatus = pair.status;
  const isProcessing = pairStatus === 'generating' || pairStatus === 'scoring';

  return (
    <>
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="flex">
          {/* Original */}
          <div className="flex-1 p-3">
            <p className="text-xs text-muted-foreground mb-1.5 font-medium">Original</p>
            {originalThumb ? (
              <div
                className="aspect-square bg-muted rounded-lg overflow-hidden cursor-pointer relative group"
                onClick={() => originalFullUrl && setLightboxImage(originalFullUrl)}
              >
                <img src={originalThumb} alt="Original" className="w-full h-full object-cover" />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors flex items-center justify-center">
                  <Maximize2 className="h-5 w-5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
              </div>
            ) : (
              <div className="aspect-square bg-muted rounded-lg flex items-center justify-center">
                <span className="text-xs text-muted-foreground">No image</span>
              </div>
            )}
          </div>

          {/* Generated */}
          <div className="flex-1 p-3">
            <p className="text-xs text-muted-foreground mb-1.5 font-medium">Generated</p>
            {generatedThumb ? (
              <div
                className="aspect-square bg-muted rounded-lg overflow-hidden cursor-pointer relative group"
                onClick={() => setLightboxImage(
                  generationApi.getEvalGeneratedImageUrl(evalId, pair.id)
                )}
              >
                <img src={generatedThumb} alt="Generated" className="w-full h-full object-cover" />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors flex items-center justify-center">
                  <Maximize2 className="h-5 w-5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
              </div>
            ) : isProcessing ? (
              <div className="aspect-square bg-muted rounded-lg flex items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="aspect-square bg-muted rounded-lg flex items-center justify-center">
                {pairStatus === 'failed' ? (
                  <XCircle className="h-5 w-5 text-red-500" />
                ) : (
                  <span className="text-xs text-muted-foreground">Pending</span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Scores */}
        <div className="px-3 pb-3 space-y-2">
          {pair.pair_score !== null && (
            <div className={cn('text-center py-1.5 rounded-lg', scoreBg(pair.pair_score))}>
              <span className={cn('text-lg font-bold', scoreColor(pair.pair_score))}>
                {pair.pair_score.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground ml-1">/ 10</span>
            </div>
          )}

          <ScoreBar label="Embedding Similarity" score={pair.embedding_similarity} />
          <ScoreBar label="Vision Score" score={pair.vision_score} />

          {pair.metrics_detail && (
            <>
              <ScoreBar label="Style Fidelity" score={pair.metrics_detail.style_fidelity ?? null} />
              <ScoreBar label="Subject Accuracy" score={pair.metrics_detail.subject_accuracy ?? null} />
              <ScoreBar label="Detail Preservation" score={pair.metrics_detail.detail_preservation ?? null} />
            </>
          )}

          {pair.error_message && (
            <p className="text-xs text-red-600 dark:text-red-400">{pair.error_message}</p>
          )}

          {(pair.vision_assessment || pair.prompt_used) && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {expanded ? 'Less' : 'More details'}
            </button>
          )}

          {expanded && (
            <div className="space-y-2 text-xs">
              {pair.vision_assessment && (
                <div>
                  <p className="font-medium text-muted-foreground mb-0.5">AI Assessment</p>
                  <p className="text-foreground">{pair.vision_assessment}</p>
                </div>
              )}
              {pair.prompt_used && (
                <div>
                  <p className="font-medium text-muted-foreground mb-0.5">Prompt Used</p>
                  <p className="text-foreground line-clamp-4">{pair.prompt_used}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Lightbox */}
      {lightboxImage && (
        <div
          className="fixed inset-0 bg-black/80 z-[60] flex items-center justify-center cursor-pointer"
          onClick={() => setLightboxImage(null)}
        >
          <img
            src={lightboxImage}
            alt="Full size"
            className="max-w-[90vw] max-h-[90vh] object-contain"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}

export default function EvaluationResultsPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const loraId = Number(params.id);
  const evalId = Number(params.evalId);
  const [showTrainingConfig, setShowTrainingConfig] = useState(false);

  const { data: evaluation, isLoading } = useQuery({
    queryKey: ['evaluation', evalId],
    queryFn: () => generationApi.getEvaluation(evalId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'pending' || status === 'running' ? 5000 : false;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => generationApi.deleteEvaluation(evalId),
    onSuccess: () => {
      toast.success('Evaluation deleted');
      queryClient.invalidateQueries({ queryKey: ['evaluations', loraId] });
      router.push(`/models/${loraId}/evaluate`);
    },
    onError: () => toast.error('Failed to delete evaluation'),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!evaluation) {
    return (
      <div className="max-w-4xl mx-auto py-8 text-center text-muted-foreground">
        Evaluation not found
      </div>
    );
  }

  const isRunning = evaluation.status === 'pending' || evaluation.status === 'running';
  const completedPairs = evaluation.pairs.filter((p) => p.status === 'completed');
  const failedPairs = evaluation.pairs.filter((p) => p.status === 'failed');

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            href={`/models/${loraId}/evaluate`}
            className="p-2 hover:bg-muted rounded-lg transition-colors"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <FlaskConical className="h-6 w-6 text-amber-600" />
              Evaluation Results
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              {evaluation.lora_model_name} · {evaluation.sample_count} samples · {formatDate(evaluation.created_at)}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isRunning && (
            <span className="flex items-center gap-1.5 text-sm text-blue-600">
              <Loader2 className="h-4 w-4 animate-spin" />
              {evaluation.status === 'pending' ? 'Queued' : 'Running'}
              {evaluation.pairs.length > 0 && (
                <span className="text-muted-foreground">
                  ({completedPairs.length}/{evaluation.sample_count})
                </span>
              )}
            </span>
          )}
          <button
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
            className="p-2 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors text-muted-foreground hover:text-red-600"
            title="Delete evaluation"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Score Header */}
      {evaluation.overall_score !== null && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className={cn('rounded-xl p-5 text-center', scoreBg(evaluation.overall_score))}>
            <p className="text-xs text-muted-foreground font-medium mb-1">Overall Score</p>
            <p className={cn('text-4xl font-bold', scoreColor(evaluation.overall_score))}>
              {evaluation.overall_score.toFixed(1)}
            </p>
            <p className="text-xs text-muted-foreground mt-1">/ 10</p>
          </div>
          <div className="bg-card border border-border rounded-xl p-5 text-center">
            <p className="text-xs text-muted-foreground font-medium mb-1">Embedding Similarity</p>
            <p className={cn('text-2xl font-bold', scoreColor(evaluation.avg_embedding_similarity))}>
              {evaluation.avg_embedding_similarity !== null ? evaluation.avg_embedding_similarity.toFixed(1) : '—'}
            </p>
          </div>
          <div className="bg-card border border-border rounded-xl p-5 text-center">
            <p className="text-xs text-muted-foreground font-medium mb-1">Vision Score</p>
            <p className={cn('text-2xl font-bold', scoreColor(evaluation.avg_vision_score))}>
              {evaluation.avg_vision_score !== null ? evaluation.avg_vision_score.toFixed(1) : '—'}
            </p>
          </div>
          <div className="bg-card border border-border rounded-xl p-5 text-center">
            <p className="text-xs text-muted-foreground font-medium mb-1">Pairs</p>
            <p className="text-2xl font-bold text-foreground">
              {completedPairs.length}
              <span className="text-sm text-muted-foreground font-normal">
                /{evaluation.sample_count}
              </span>
            </p>
            {failedPairs.length > 0 && (
              <p className="text-xs text-red-500 mt-1">{failedPairs.length} failed</p>
            )}
          </div>
        </div>
      )}

      {/* Training Parameters */}
      {evaluation.training_config && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <button
            onClick={() => setShowTrainingConfig(!showTrainingConfig)}
            className="w-full flex items-center justify-between p-4 hover:bg-muted/50 transition-colors"
          >
            <span className="text-sm font-medium">Training Parameters</span>
            {showTrainingConfig ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
          {showTrainingConfig && (
            <div className="px-4 pb-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                {Object.entries(evaluation.training_config).map(([key, value]) => (
                  <div key={key}>
                    <span className="text-muted-foreground text-xs">{key}</span>
                    <p className="font-medium">{String(value)}</p>
                  </div>
                ))}
                <div>
                  <span className="text-muted-foreground text-xs">training_images</span>
                  <p className="font-medium">{evaluation.training_images_count}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* AI Assessment */}
      {evaluation.assessment_summary && (
        <div className="bg-card border border-border rounded-xl p-5">
          <h3 className="text-sm font-medium mb-2">AI Assessment</h3>
          <blockquote className="border-l-4 border-amber-500 pl-4 text-sm text-muted-foreground italic">
            {evaluation.assessment_summary}
          </blockquote>
        </div>
      )}

      {/* Error */}
      {evaluation.error_message && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4">
          <p className="text-sm text-red-700 dark:text-red-400">
            <span className="font-medium">Error:</span> {evaluation.error_message}
          </p>
        </div>
      )}

      {/* Side-by-side Comparison Grid */}
      {evaluation.pairs.length > 0 && (
        <div>
          <h3 className="text-lg font-semibold mb-4">Comparisons</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {evaluation.pairs.map((pair) => (
              <PairCard key={pair.id} pair={pair} evalId={evalId} />
            ))}
          </div>
        </div>
      )}

      {/* Empty state while running */}
      {isRunning && evaluation.pairs.length === 0 && (
        <div className="text-center py-16 text-muted-foreground">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-3 text-amber-600" />
          <p>Generating and scoring images...</p>
          <p className="text-sm mt-1">This may take a few minutes depending on sample count</p>
        </div>
      )}
    </div>
  );
}
