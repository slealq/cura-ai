'use client';

import { imagesApi } from '@/lib/api';
import ImageGrid from '@/components/ImageGrid';

export default function AllImagesPage() {
  return (
    <ImageGrid
      title="All Images"
      queryKeyPrefix="all-images"
      fetchImages={(params) => imagesApi.list(params)}
    />
  );
}
