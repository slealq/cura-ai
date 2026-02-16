'use client';

import Link from 'next/link';
import { FolderOpen, Image as ImageIcon } from 'lucide-react';
import type { Folder } from '@/types';
import { authUrl } from '@/lib/api';

interface FolderCardProps {
  folder: Folder;
}

export default function FolderCard({ folder }: FolderCardProps) {
  // For Azure SAS URLs (https://...) use directly; for local (/api/...) wrap with authUrl
  const coverSrc = folder.cover_thumbnail_url
    ? folder.cover_thumbnail_url.startsWith('http')
      ? folder.cover_thumbnail_url
      : authUrl(folder.cover_thumbnail_url)
    : null;

  return (
    <Link href={`/images/folder/${folder.id}`}>
      <div className="group bg-card rounded-xl border border-border overflow-hidden hover:shadow-lg transition-shadow">
        {/* Cover Image */}
        <div className="aspect-video bg-muted relative">
          {coverSrc ? (
            <img
              src={coverSrc}
              alt=""
              loading="lazy"
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            />
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
