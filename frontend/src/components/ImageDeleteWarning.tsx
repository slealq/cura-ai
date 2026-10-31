'use client';

import { useQuery } from '@tanstack/react-query';
import { historyApi } from '@/lib/api';

export default function ImageDeleteWarning({ imageIds = [], folderId }: { imageIds?: number[]; folderId?: number }) {
  const { data, isError } = useQuery({
    queryKey: ['delete-used-by', imageIds, folderId],
    queryFn: () => historyApi.usedBy(imageIds, folderId),
    staleTime: 0,
  });
  if (isError) return <p className="text-sm text-muted-foreground">Could not check whether other images use these.</p>;
  if (!data?.count) return null;
  const single = imageIds.length === 1;
  const made = data.count === 1 ? '1 image' : `${data.count} images`;
  return <p className="text-sm text-destructive">
    <b className="font-medium">{single ? 'It was' : 'These were'} used to make {made}.</b>{' '}
    {data.count === 1 ? 'That image' : 'Those images'} will keep a low-resolution copy in {data.count === 1 ? 'its' : 'their'} history, but the {single ? 'original' : 'originals'} will be gone.
  </p>;
}
