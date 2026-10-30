'use client';

import { imagesApi } from '@/lib/api';
import ImageGrid from '@/components/ImageGrid';

export default function ImagesPage() {
  return (
    <ImageGrid
      title="All images"
      queryKeyPrefix="library-images"
      fetchImages={(params) => imagesApi.list(params)}
      showSourceFilter
    />
  );
}
