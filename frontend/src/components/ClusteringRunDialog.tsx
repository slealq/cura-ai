'use client';

import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { clustersApi, settingsApi } from '@/lib/api';
import type { ClusteringConfig } from '@/types';

const control = 'w-full rounded-lg border border-border bg-background px-3 py-2 text-sm';

const numericFields = {
  umap_n_components: {
    label: 'Components', min: 2, max: 50, step: 1,
    legend: 'Number of dimensions after reduction.',
  },
  umap_n_neighbors: {
    label: 'Neighbors', min: 2, max: 100, step: 1,
    legend: 'Nearby points considered by UMAP.',
  },
  umap_min_dist: {
    label: 'Minimum distance', min: 0, max: 1, step: 0.01,
    legend: 'Controls spacing in the reduced representation.',
  },
  hdbscan_min_cluster_size: {
    label: 'Minimum cluster size', min: 2, max: 100, step: 1,
    legend: 'Smallest group eligible to form a cluster.',
  },
  hdbscan_min_samples: {
    label: 'Minimum samples', min: 1, max: 50, step: 1,
    legend: 'Controls how much neighborhood density is required.',
  },
  kmeans_max_clusters: {
    label: 'Maximum clusters', min: 2, max: 200, step: 1,
    legend: 'Upper bound for automatic K selection. K is capped at 20 and by the available sample count.',
  },
} as const;

type NumericKey = keyof typeof numericFields;
type NumericDraft = Record<NumericKey, string>;
type Props = {
  hasClusters: boolean;
  onClose: () => void;
  onStarted: (jobId: number) => void;
};

function numericDraft(config: ClusteringConfig): NumericDraft {
  return Object.fromEntries(
    (Object.keys(numericFields) as NumericKey[]).map((key) => [key, String(config[key])])
  ) as NumericDraft;
}

function validatedConfig(config: ClusteringConfig, raw: NumericDraft): ClusteringConfig | null {
  const result = { ...config };
  for (const key of Object.keys(numericFields) as NumericKey[]) {
    const { min, max, step } = numericFields[key];
    const value = Number(raw[key]);
    if (
      raw[key].trim() === '' ||
      !Number.isFinite(value) ||
      value < min ||
      value > max ||
      (step === 1 && !Number.isInteger(value))
    ) {
      return null;
    }
    result[key] = value;
  }
  if (
    !['hdbscan', 'kmeans', 'graph'].includes(result.method) ||
    !['cosine', 'euclidean'].includes(result.umap_metric) ||
    !['eom', 'leaf'].includes(result.hdbscan_cluster_selection_method)
  ) {
    return null;
  }
  return result;
}

export default function ClusteringRunDialog({ hasClusters, onClose, onStarted }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const submitting = useRef(false);
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<ClusteringConfig | null>(null);
  const [numbers, setNumbers] = useState<NumericDraft | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const element = dialog.current!;
    const trigger = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    element.showModal();
    return () => {
      element.close();
      document.body.style.overflow = previousOverflow;
      trigger?.focus();
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    settingsApi.getClusteringConfig()
      .then((config) => {
        if (active) {
          queryClient.setQueryData(['clustering-config'], config);
          setDraft(config);
          setNumbers(numericDraft(config));
        }
      })
      .catch(() => {
        if (active) setError('Could not load clustering settings. Please try again.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [attempt, queryClient]);

  const update = (values: Partial<ClusteringConfig>) => {
    setDraft((current) => current && { ...current, ...values });
  };

  const run = async () => {
    if (!draft || !numbers || submitting.current) return;
    const config = validatedConfig(draft, numbers);
    if (!config) {
      setAdvancedOpen(true);
      setError('Check that all parameters have valid values within their indicated ranges.');
      return;
    }
    submitting.current = true;
    setPending(true);
    setError('');
    try {
      const saved = await settingsApi.updateClusteringConfig(config);
      queryClient.setQueryData(['clustering-config'], saved);
      setDraft(saved);
      setNumbers(numericDraft(saved));
    } catch {
      setError('Could not save clustering settings. Clustering was not started. Please try again.');
      submitting.current = false;
      setPending(false);
      return;
    }
    try {
      const result = await clustersApi.recluster();
      void queryClient.invalidateQueries({ queryKey: ['clustering-config'] });
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      onStarted(result.job_id);
    } catch {
      setError('Settings were saved, but clustering could not be started. Please try again.');
      void queryClient.invalidateQueries({ queryKey: ['clustering-config'] });
      submitting.current = false;
      setPending(false);
    }
  };

  const numberField = (key: NumericKey) => {
    const { label, min, max, step, legend } = numericFields[key];
    return (
      <label className="block space-y-1 text-sm">
        <span className="font-medium">{label}</span>
        <span className="block text-xs text-muted-foreground">{legend} ({min}–{max})</span>
        <input
          className={control}
          type="number"
          min={min}
          max={max}
          step={step}
          value={numbers?.[key] ?? ''}
          onChange={(e) => {
            const value = e.target.value;
            setNumbers((current) => current && { ...current, [key]: value });
          }}
        />
      </label>
    );
  };

  return (
    <dialog
      ref={dialog}
      aria-labelledby="clustering-dialog-title"
      onKeyDown={(e) => {
        if (e.key !== 'Tab') return;
        const focusable = Array.from(
          e.currentTarget.querySelectorAll<HTMLElement>(
            'button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, [tabindex]:not([tabindex="-1"])'
          )
        ).filter((element) =>
          element.getClientRects().length > 0 && !element.matches(':disabled') && !element.closest('fieldset:disabled')
        );
        if (focusable.length === 0) {
          e.preventDefault();
          return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }}
      onCancel={(e) => {
        e.preventDefault();
        if (!submitting.current) onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting.current) onClose();
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-2xl max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-xl border border-border bg-card p-0 text-card-foreground shadow-xl backdrop:bg-black/50"
    >
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
        className="space-y-5 p-6"
      >
        <h2 id="clustering-dialog-title" className="text-lg font-semibold">Run Clustering</h2>
        {hasClusters && (
          <p className="rounded-lg bg-amber-500/10 p-3 text-sm">
            Existing clusters will be replaced. Save important clusters as folders first.
          </p>
        )}
        {loading && <p className="text-sm text-muted-foreground">Loading saved settings...</p>}
        {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        {!loading && !draft && (
          <button type="button" className="text-sm underline" onClick={() => setAttempt((v) => v + 1)}>
            Retry loading settings
          </button>
        )}
        {draft && (
          <fieldset disabled={pending} className="space-y-5 disabled:opacity-60">
            <label className="block space-y-1 text-sm">
              <span className="font-medium">Method</span>
              <span className="block text-xs text-muted-foreground">
                HDBSCAN finds density-based groups; K-Means assigns images to groups; Graph detects communities by similarity.
              </span>
              <select className={control} value={draft.method} onChange={(e) => update({ method: e.target.value })}>
                <option value="hdbscan">HDBSCAN</option>
                <option value="kmeans">K-Means</option>
                <option value="graph">Graph (Louvain)</option>
              </select>
            </label>
            <details className="rounded-lg border border-border p-4" open={advancedOpen} onToggle={(e) => setAdvancedOpen(e.currentTarget.open)}>
              <summary
                className="cursor-pointer text-sm font-medium"
                onClick={(e) => { if (pending) e.preventDefault(); }}
              >
                Advanced parameters
              </summary>
              <div className="mt-4 space-y-4">
                <label className="flex items-center gap-2 text-sm font-medium">
                  <input type="checkbox" checked={draft.use_umap} onChange={(e) => update({ use_umap: e.target.checked })} />
                  Use UMAP dimensionality reduction
                </label>
                <p className="text-xs text-muted-foreground">
                  UMAP reduces embedding dimensions before clustering. Parameters are limited automatically for small collections; UMAP is skipped for fewer than 4 images.
                </p>
                {draft.use_umap && (
                  <div className="grid gap-4 sm:grid-cols-2">
                    {numberField('umap_n_components')}
                    {numberField('umap_n_neighbors')}
                    {numberField('umap_min_dist')}
                    <label className="block space-y-1 text-sm">
                      <span className="font-medium">Metric</span>
                      <span className="block text-xs text-muted-foreground">Distance measure used by UMAP.</span>
                      <select className={control} value={draft.umap_metric} onChange={(e) => update({ umap_metric: e.target.value })}>
                        <option value="cosine">Cosine</option>
                        <option value="euclidean">Euclidean</option>
                      </select>
                    </label>
                  </div>
                )}
                {draft.method === 'hdbscan' && (
                  <div className="grid gap-4 sm:grid-cols-2">
                    {numberField('hdbscan_min_cluster_size')}
                    {numberField('hdbscan_min_samples')}
                    <label className="block space-y-1 text-sm">
                      <span className="font-medium">Selection method</span>
                      <span className="block text-xs text-muted-foreground">EOM selects stable groups; Leaf selects from the hierarchy’s leaves.</span>
                      <select className={control} value={draft.hdbscan_cluster_selection_method} onChange={(e) => update({ hdbscan_cluster_selection_method: e.target.value })}>
                        <option value="eom">EOM</option>
                        <option value="leaf">Leaf</option>
                      </select>
                    </label>
                  </div>
                )}
                {draft.method === 'kmeans' && numberField('kmeans_max_clusters')}
              </div>
            </details>
          </fieldset>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" disabled={pending} onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted disabled:opacity-50">
            Cancel
          </button>
          <button type="submit" disabled={!draft || loading || pending} className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            {pending ? 'Starting...' : 'Run Clustering'}
          </button>
        </div>
      </form>
    </dialog>
  );
}
