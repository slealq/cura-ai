'use client';

import { createElement, useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { clearDeleting } from '@/lib/deletingImages';
import { useNotifications } from '@/contexts/NotificationContext';
import JobBanner from '@/components/JobBanner';
import { toast } from 'sonner';
import { billingApi, jobsApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { trackFunnelStep } from '@/lib/observability';
import type { Job } from '@/types';

const JOB_TYPE_LABELS: Record<string, string> = {
  ingest: 'Upload',
  tag: 'Tagging',
  describe: 'Description',
  embed: 'Embedding',
  cluster: 'Clustering',
  summarize_cluster: 'Summarization',
  full_pipeline: 'Full Pipeline',
  reprocess: 'Describe',
  batch_reprocess: 'Batch Describe',
  batch_describe: 'Batch Describe',
  lora_train: 'LoRA Training',
  edit_image: 'Edit',
  batch_edit: 'Edit',
  generate_image: 'Image Generation',
  batch_generate: 'Batch Generation',
  lora_evaluate: 'LoRA Evaluation',
  folder_delete: 'Folder Delete',
  image_delete: 'Image Delete',
};

export function jobLabel(job: Job): string {
  return JOB_TYPE_LABELS[job.job_type] || job.job_type.replace('_', ' ');
}

// Job types that may create/modify folders — refresh folder list on completion
const FOLDER_AFFECTING_JOBS = new Set(['ingest', 'folder_delete', 'image_delete']);

// Job types that replace/update clusters — refresh cluster list on completion
const CLUSTER_AFFECTING_JOBS = new Set(['cluster', 'summarize_cluster']);

export function useJobNotifications() {
  const { ready, preferences, recordJob } = useNotifications();
  const finishedRef = useRef<{ jobs: Job[]; at: number }>({ jobs: [], at: 0 });
  const lowBalanceRef = useRef(false);
  const failuresRef = useRef<Set<number>>(new Set());
  const queryClient = useQueryClient();
  const { isAuthenticated } = useAuth();
  const statusMapRef = useRef<Map<number, string>>(new Map());
  const initializedRef = useRef(false);

  useEffect(() => {
    const failures = failuresRef.current;
    return () => {
      toast.dismiss('jobs-finished');
      toast.dismiss('low-balance');
      failures.forEach(id => toast.dismiss(`job-failed-${id}`));
    };
  }, []);

  const { data: balance } = useQuery({
    queryKey: ['billing', 'balance'],
    queryFn: billingApi.getBalance,
    refetchInterval: 30000,
    enabled: isAuthenticated,
  });

  useEffect(() => {
    if (!ready || !balance) return;
    const available = balance.available ?? balance.balance - (balance.reserved ?? 0);
    if (available >= 200) {
      lowBalanceRef.current = false;
      toast.dismiss('low-balance');
    } else if (preferences.lowBalance && !lowBalanceRef.current) {
      lowBalanceRef.current = true;
      toast(`You have ${Math.floor(available)} sparks left`, {
        id: 'low-balance',
        description: 'Add sparks to keep creating.',
        duration: 4500,
        action: { label: 'Add', onClick: () => { window.location.href = '/billing#add-sparks'; } },
      });
    }
    if (!preferences.lowBalance) toast.dismiss('low-balance');
  }, [balance, preferences.lowBalance, ready]);

  useEffect(() => {
    if (!preferences.finished) {
      toast.dismiss('jobs-finished');
      finishedRef.current = { jobs: [], at: 0 };
    }
    if (!preferences.failed) {
      failuresRef.current.forEach(id => toast.dismiss(`job-failed-${id}`));
      failuresRef.current.clear();
    }
  }, [preferences.finished, preferences.failed]);

  const { data } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => jobsApi.list({ limit: 50 }),
    refetchInterval: 5000,
    enabled: isAuthenticated,
  });

  useEffect(() => {
    if (!ready || !data?.items) return;

    const jobs = data.items;
    const prevMap = statusMapRef.current;

    if (!initializedRef.current) {
      // First load: populate map without notifying old jobs
      for (const job of jobs) {
        prevMap.set(job.id, job.status);
      }
      initializedRef.current = true;
      return;
    }

    for (const job of jobs) {
      const prev = prevMap.get(job.id);
      prevMap.set(job.id, job.status);

      // Skip if status hasn't changed or this is a brand new job
      if (!prev || prev === job.status) continue;

      if (job.status === 'failed') {
        if (job.job_type === 'image_delete') clearDeleting();
        recordJob();
        if (preferences.failed) {
          failuresRef.current.add(job.id);
          toast.custom(id => createElement(JobBanner, {
            title: `${jobLabel(job)} failed`,
            description: job.error_message || `Job #${job.id} failed.`,
            failedJob: job,
            onDismiss: () => toast.dismiss(id),
          }), { id: `job-failed-${job.id}`, duration: Infinity });
        }
      } else if (job.status === 'completed' && (prev === 'running' || prev === 'pending')) {
        recordJob();
        if (preferences.finished) {
          const now = Date.now();
          const group = finishedRef.current;
          const finished = now - group.at < 6000 ? [...group.jobs, job] : [job];
          finishedRef.current = { jobs: finished, at: now };
          const count = finished.reduce((total, item) => {
            const ids = item.result?.generated_image_ids ?? item.result?.image_ids;
            return total + (Array.isArray(ids) ? ids.length : item.total_items || 1);
          }, 0);
          const costs = finished.map(item => item.charged_sparks);
          const cost = costs.every(value => value != null)
            ? `${costs.reduce<number>((total, value) => total + (value ?? 0), 0).toLocaleString()} sparks`
            : 'Cost available in Jobs';
          toast.custom(id => createElement(JobBanner, {
            title: finished.length > 1 ? `${finished.length} jobs finished` : `${jobLabel(job)} finished`,
            description: `${count} ${count === 1 ? 'item' : 'items'}, ${cost}`,
            job: finished.find(item => item.image_thumbnail) ?? finished[0],
            thumbnail: finished.find(item => item.image_thumbnail)?.image_thumbnail,
            onDismiss: () => toast.dismiss(id),
          }), { id: 'jobs-finished', duration: 4500 });
        }

        // Track funnel completion events
        if (job.job_type === 'ingest') {
          trackFunnelStep('upload', 'images_visible', { jobId: job.id });
        }
        if (job.job_type === 'lora_train') {
          trackFunnelStep('training', 'training_complete', { jobId: job.id });
        }

        // Every grid and count can include a deleted image
        if (job.job_type === 'image_delete') queryClient.invalidateQueries();

        // Refresh folder list when ingest/delete jobs complete (deferred folder assignment)
        if (FOLDER_AFFECTING_JOBS.has(job.job_type)) {
          queryClient.invalidateQueries({ queryKey: ['folders'] });
          queryClient.invalidateQueries({ queryKey: ['images'] });
          queryClient.invalidateQueries({ queryKey: ['library-images'] });
          queryClient.invalidateQueries({ queryKey: ['all-images'] });
          queryClient.invalidateQueries({ queryKey: ['stats'] });
        }

        // Refresh cluster list when clustering completes
        if (CLUSTER_AFFECTING_JOBS.has(job.job_type)) {
          queryClient.invalidateQueries({ queryKey: ['clusters'] });
        }

        // Clean up sessionStorage tracking for completed folder deletes
        if (job.job_type === 'folder_delete') {
          try {
            const fId = job.parameters?.folder_id as number | undefined;
            if (fId) {
              const raw = sessionStorage.getItem('deleting-folders');
              if (raw) {
                const ids = (JSON.parse(raw) as number[]).filter((id) => id !== fId);
                if (ids.length > 0) {
                  sessionStorage.setItem('deleting-folders', JSON.stringify(ids));
                } else {
                  sessionStorage.removeItem('deleting-folders');
                }
              }
            }
          } catch {
            // Ignore sessionStorage errors
          }
        }
      }
    }
  }, [data, ready, queryClient, preferences.finished, preferences.failed, recordJob]);
}
