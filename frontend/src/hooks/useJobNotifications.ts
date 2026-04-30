'use client';

import { useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { jobsApi } from '@/lib/api';
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
  generate_image: 'Image Generation',
  batch_generate: 'Batch Generation',
  lora_evaluate: 'LoRA Evaluation',
  folder_delete: 'Folder Delete',
};

function jobLabel(job: Job): string {
  return JOB_TYPE_LABELS[job.job_type] || job.job_type.replace('_', ' ');
}

// Job types that may create/modify folders — refresh folder list on completion
const FOLDER_AFFECTING_JOBS = new Set(['ingest', 'folder_delete']);

// Job types that replace/update clusters — refresh cluster list on completion
const CLUSTER_AFFECTING_JOBS = new Set(['cluster', 'summarize_cluster']);

export function useJobNotifications() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isAuthenticated } = useAuth();
  const statusMapRef = useRef<Map<number, string>>(new Map());
  const initializedRef = useRef(false);

  const { data } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => jobsApi.list({ limit: 50 }),
    refetchInterval: 5000,
    enabled: isAuthenticated,
  });

  useEffect(() => {
    if (!data?.items) return;

    const jobs = data.items;
    const prevMap = statusMapRef.current;

    if (!initializedRef.current) {
      // First load: populate map without firing toasts
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
        toast.error(`${jobLabel(job)} failed`, {
          description: job.error_message || `Job #${job.id}`,
          action: {
            label: 'View',
            onClick: () => router.push('/jobs'),
          },
          duration: 8000,
        });
      } else if (job.status === 'completed' && (prev === 'running' || prev === 'pending')) {
        toast.success(`${jobLabel(job)} completed`, {
          description: `Job #${job.id}`,
          duration: 3000,
        });

        // Track funnel completion events
        if (job.job_type === 'ingest') {
          trackFunnelStep('upload', 'images_visible', { jobId: job.id });
        }
        if (job.job_type === 'lora_train') {
          trackFunnelStep('training', 'training_complete', { jobId: job.id });
        }

        // Refresh folder list when ingest/delete jobs complete (deferred folder assignment)
        if (FOLDER_AFFECTING_JOBS.has(job.job_type)) {
          queryClient.invalidateQueries({ queryKey: ['folders'] });
          queryClient.invalidateQueries({ queryKey: ['images'] });
          queryClient.invalidateQueries({ queryKey: ['unfiled-images'] });
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
  }, [data, router, queryClient]);
}
