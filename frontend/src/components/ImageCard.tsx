'use client';

import type { Image } from '@/types';
import { imagesApi } from '@/lib/api';
import { cn } from '@/lib/utils';
import { Check } from 'lucide-react';
import PipelineProgress from './PipelineProgress';

interface ImageCardProps {
  image: Image;
  onClick?: () => void;
  showStatus?: boolean;
  selectable?: boolean;
  selected?: boolean;
  onSelect?: (id: number) => void;
  score?: number;
}

export default function ImageCard({
  image,
  onClick,
  showStatus = false,
  selectable = false,
  selected = false,
  onSelect,
  score,
}: ImageCardProps) {
  const thumbnailUrl = image.thumbnail_uri_medium
    ? imagesApi.getThumbnailUrl(image.thumbnail_uri_medium.split('/').pop()!)
    : null;

  const handleClick = () => {
    if (selectable && onSelect) {
      onSelect(image.id);
    } else if (onClick) {
      onClick();
    }
  };

  return (
    <div
      onClick={handleClick}
      className={cn(
        'group relative bg-muted rounded-lg overflow-hidden aspect-square',
        (onClick || selectable) && 'cursor-pointer',
        selected && 'ring-2 ring-primary ring-offset-2'
      )}
    >
      {thumbnailUrl ? (
        <img
          src={thumbnailUrl}
          alt={image.original_filename || ''}
          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-muted-foreground">
          No preview
        </div>
      )}

      {/* Selection checkbox */}
      {selectable && (
        <div
          className={cn(
            'absolute top-2 left-2 h-5 w-5 rounded border-2 flex items-center justify-center transition-colors z-10',
            selected
              ? 'bg-primary border-primary text-primary-foreground'
              : 'border-white/80 bg-black/30'
          )}
        >
          {selected && <Check className="h-3 w-3" />}
        </div>
      )}

      {/* Hover overlay */}
      {(onClick || selectable) && (
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors" />
      )}

      {/* Search score badge */}
      {score != null && (
        <div className="absolute top-2 right-2 bg-black/60 backdrop-blur-sm text-white text-[10px] font-medium px-1.5 py-0.5 rounded-full z-10">
          {Math.round(score * 100)}%
        </div>
      )}

      {/* Pipeline progress dots */}
      {showStatus && (
        <div className="absolute top-2 right-2 bg-black/50 rounded-full px-2 py-1">
          <PipelineProgress status={image.status} variant="compact" />
        </div>
      )}

      {/* Description on hover */}
      {image.metadata?.description_long && onClick && !selectable && (
        <div className="absolute bottom-0 left-0 right-0 p-2 bg-gradient-to-t from-black/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
          <p className="text-white text-xs line-clamp-2">
            {image.metadata.description_long}
          </p>
        </div>
      )}
    </div>
  );
}
