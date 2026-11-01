'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import LibraryImage from '@/components/LibraryImage';
import { generationApi, imagesApi, jobsApi } from '@/lib/api';
import type { Job } from '@/types';

// Provider errors arrive as raw validation dumps, so show only the message inside.
function readable(text: string) {
  return text.match(/'msg':\s*'([^']+)'/)?.[1] ?? text;
}

export default function JobBanner({ title, description, thumbnail, job, failedJob, onDismiss }: {
  title: string;
  description: string;
  thumbnail?: string | null;
  job?: Job;
  failedJob?: Job;
  onDismiss: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [retrying, setRetrying] = useState(false);
  const generatedId = job?.result?.generated_image_id ?? job?.parameters?.generated_image_id
    ?? (job?.result?.generated_image_ids as number[] | undefined)?.[0]
    ?? (job?.parameters?.generated_image_ids as number[] | undefined)?.[0];
  const { data: resultThumbnail } = useQuery({
    queryKey: ['job-banner-thumbnail', job?.id],
    enabled: !!job && !thumbnail && (!!generatedId || Array.isArray(job.result?.image_ids)),
    retry: false,
    queryFn: async () => {
      if (typeof generatedId === 'number') {
        const image = await generationApi.getImage(generatedId);
        return image.thumbnail_uri_small
          ? generationApi.getThumbnailUrl(image.thumbnail_uri_small.split('/').pop()!) : null;
      }
      const images = await jobsApi.getJobImages(job!.id);
      const first = images.find(image => image.thumbnail);
      return first?.thumbnail ? imagesApi.getThumbnailUrl(first.thumbnail) : null;
    },
  });
  const preview = thumbnail ? imagesApi.getThumbnailUrl(thumbnail) : resultThumbnail;

  async function act() {
    if (!failedJob) {
      router.push('/jobs');
      onDismiss();
      return;
    }
    setRetrying(true);
    try {
      const loraId = failedJob.parameters?.lora_model_id;
      if (failedJob.job_type === 'lora_train' && typeof loraId === 'number') {
        await generationApi.retryLoraTraining(loraId);
      } else {
        await jobsApi.retry(failedJob.id);
      }
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      toast.success('Job retry started');
      onDismiss();
    } catch (error) {
      toast.error('Retry failed', { description: error instanceof Error ? error.message : 'Please try again.' });
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div role="status" className="flex w-full items-center gap-3 rounded-lg border border-border bg-background p-3 text-foreground shadow-lg">
      {preview && <LibraryImage src={preview} alt="Job result" className="h-12 w-12 shrink-0 rounded-md object-cover" />}
      <div className="min-w-0 flex-1">
        <p className={`text-sm font-semibold ${failedJob ? 'text-danger' : ''}`}>{title}</p>
        <p className="line-clamp-3 break-words text-xs text-muted-foreground">{readable(description)}</p>
      </div>
      <button onClick={act} disabled={retrying} className="min-h-10 px-2 text-sm font-medium disabled:opacity-50">
        {failedJob ? retrying ? 'Retrying…' : 'Retry' : 'View'}
      </button>
      <button onClick={onDismiss} aria-label="Dismiss notification" className="min-h-10 min-w-10 text-lg">×</button>
    </div>
  );
}
