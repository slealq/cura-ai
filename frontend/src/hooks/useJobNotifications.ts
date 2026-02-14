'use client';

import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { jobsApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import type { Job } from '@/types';

const JOB_TYPE_LABELS: Record<string, string> = {
  tag: 'Tagging',
  describe: 'Description',
  embed: 'Embedding',
  cluster: 'Clustering',
  summarize_cluster: 'Summarization',
  full_pipeline: 'Full Pipeline',
  reprocess: 'Reprocess',
  batch_reprocess: 'Batch Reprocess',
  lora_train: 'LoRA Training',
  generate_image: 'Image Generation',
  batch_generate: 'Batch Generation',
  lora_evaluate: 'LoRA Evaluation',
};

function jobLabel(job: Job): string {
  return JOB_TYPE_LABELS[job.job_type] || job.job_type.replace('_', ' ');
}

export function useJobNotifications() {
  const router = useRouter();
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
      }
    }
  }, [data, router]);
}
