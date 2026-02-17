'use client';

import { Loader2, AlertCircle, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { GeneratedImage } from '@/types';
import { generationApi } from '@/lib/api';

const statusStyles: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-700 dark:bg-gray-900/50 dark:text-gray-300',
  generating: 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300',
  completed: 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300',
  failed: 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300',
};

const modelBadgeStyles: Record<string, string> = {
  'flux-dev': 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300',
  'qwen-2.5': 'bg-orange-100 text-orange-700 dark:bg-orange-900/50 dark:text-orange-300',
};

const modelLabels: Record<string, string> = {
  'flux-dev': 'Flux',
  'qwen-2.5': 'Qwen',
};

export default function GeneratedImageCard({
  image,
  onClick,
  onDelete,
}: {
  image: GeneratedImage;
  onClick?: () => void;
  onDelete?: (id: number) => void;
}) {
  const thumbnailSrc = image.thumbnail_uri_medium
    ? generationApi.getThumbnailUrl(image.thumbnail_uri_medium.split('/').pop() || '')
    : null;

  return (
    <div
      className={cn(
        'group relative bg-card border border-border rounded-lg overflow-hidden transition-shadow hover:shadow-md',
        onClick && 'cursor-pointer'
      )}
      onClick={onClick}
    >
      {/* Image / Placeholder */}
      <div className="aspect-square bg-muted/30 relative">
        {image.status === 'completed' && thumbnailSrc ? (
          <img
            src={thumbnailSrc}
            alt={image.prompt.slice(0, 80)}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : image.status === 'generating' || image.status === 'pending' ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : image.status === 'failed' ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <AlertCircle className="h-8 w-8 text-red-400" />
          </div>
        ) : null}

        {/* Status badge */}
        {image.status !== 'completed' && (
          <div className="absolute top-2 right-2">
            <span
              className={cn(
                'px-2 py-0.5 rounded-full text-[10px] font-semibold',
                statusStyles[image.status] || statusStyles.pending
              )}
            >
              {image.status}
            </span>
          </div>
        )}

        {/* Delete button for non-completed images */}
        {image.status !== 'completed' && onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(image.id);
            }}
            className="absolute top-2 left-2 z-10 p-1 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600"
            title="Delete image"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}

        {/* LoRA badge(s) */}
        {image.loras && image.loras.length > 0 ? (
          <div className="absolute top-2 left-2 flex flex-col gap-0.5">
            {image.loras.map((l) => (
              <span key={l.lora_model_id} className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300">
                {l.lora_model_name}
              </span>
            ))}
          </div>
        ) : image.lora_model_name ? (
          <div className="absolute top-2 left-2">
            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300">
              {image.lora_model_name}
            </span>
          </div>
        ) : null}
      </div>

      {/* Model badge */}
      {image.base_model && (
        <div className="absolute bottom-2 left-2 group-hover:opacity-0 transition-opacity">
          <span className={cn(
            'px-1.5 py-0.5 rounded-full text-[10px] font-semibold',
            modelBadgeStyles[image.base_model] || 'bg-gray-100 text-gray-700 dark:bg-gray-900/50 dark:text-gray-300'
          )}>
            {modelLabels[image.base_model] || image.base_model}
          </span>
        </div>
      )}

      {/* Prompt preview on hover */}
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent p-3 opacity-0 group-hover:opacity-100 transition-opacity">
        <p className="text-xs text-white line-clamp-2">{image.prompt}</p>
      </div>
    </div>
  );
}
