'use client';

import Link from 'next/link';
import { FolderOpen, Image as ImageIcon } from 'lucide-react';
import type { Folder } from '@/types';
import { imagesApi } from '@/lib/api';

interface FolderCardProps {
  folder: Folder;
}

export default function FolderCard({ folder }: FolderCardProps) {
  const previews = folder.preview_images.slice(0, 4);

  return (
    <Link href={`/images/folder/${folder.id}`}>
      <div className="group bg-card rounded-xl border border-border overflow-hidden hover:shadow-lg transition-shadow">
        {/* 2x2 Thumbnail Grid */}
        <div className="aspect-video bg-muted relative">
          {previews.length > 0 ? (
            <div className="grid grid-cols-2 grid-rows-2 h-full">
              {previews.map((img) => (
                <div key={img.id} className="relative overflow-hidden">
                  <img
                    src={
                      img.thumbnail_uri_medium
                        ? imagesApi.getThumbnailUrl(img.thumbnail_uri_medium.split('/').pop()!)
                        : '/placeholder.png'
                    }
                    alt=""
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                  />
                </div>
              ))}
              {/* Fill remaining slots with empty cells */}
              {Array.from({ length: 4 - previews.length }).map((_, i) => (
                <div key={`empty-${i}`} className="bg-muted" />
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center h-full">
              <ImageIcon className="h-12 w-12 text-muted-foreground/50" />
            </div>
          )}
        </div>

        {/* Content */}
        <div className="p-4">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <FolderOpen className="h-4 w-4 text-muted-foreground shrink-0" />
              <h3 className="font-medium text-sm truncate">{folder.name}</h3>
            </div>
            <span className="text-xs text-muted-foreground shrink-0">
              {folder.image_count} image{folder.image_count !== 1 ? 's' : ''}
            </span>
          </div>

          {folder.description && (
            <p className="mt-2 text-xs text-muted-foreground line-clamp-2">
              {folder.description}
            </p>
          )}
        </div>
      </div>
    </Link>
  );
}
