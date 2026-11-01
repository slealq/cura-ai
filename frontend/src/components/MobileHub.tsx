'use client';

import Link from 'next/link';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { clustersApi, foldersApi, imagesApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { useTheme } from '@/contexts/ThemeContext';
import LibraryImage from './LibraryImage';
import LibraryThumbnail from './LibraryThumbnail';
import { clusterTitle } from './ClusterTools';

function Row({ href, title, description }: { href: string; title: string; description?: string }) {
  return (
    <Link href={href} className="flex min-h-[72px] items-center gap-3 border-b border-border py-3">
      <div className="min-w-0 flex-1">
        <span className="block font-medium">{title}</span>
        {description && <span className="block text-sm text-muted-foreground">{description}</span>}
      </div>
      <span aria-hidden="true">›</span>
    </Link>
  );
}

export default function MobileHub({ kind }: { kind: 'collection' | 'studio' | 'account' }) {
  const router = useRouter();
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  useEffect(() => {
    const media = window.matchMedia('(min-width: 768px)');
    const redirect = () => {
      if (media.matches) router.replace(kind === 'collection' ? '/images' : kind === 'studio' ? '/edit' : '/settings');
    };
    redirect();
    media.addEventListener('change', redirect);
    return () => media.removeEventListener('change', redirect);
  }, [kind, router]);
  const { data: clusters, isLoading: loadingClusters, isError: clusterError } = useQuery({ queryKey: ['clusters', 'mobile-hub'], queryFn: () => clustersApi.list({ limit: 2 }), enabled: kind === 'collection' });
  const { data: folders } = useQuery({ queryKey: ['folders', 'mobile-hub'], queryFn: () => foldersApi.list({ limit: 1 }), enabled: kind === 'collection' });
  const { data: images, isLoading: loadingImages } = useQuery({ queryKey: ['images', 'mobile-hub', kind], queryFn: () => imagesApi.list({ limit: 8, ...(kind === 'studio' ? { source: 'generated' } : {}) }), enabled: kind !== 'account' });
  return (
    <div className="min-w-0 md:hidden">
      {kind === 'collection' && (
        <>
          <Link href="/search" className="flex min-h-12 w-full items-center rounded-lg border border-border bg-muted px-4 text-muted-foreground">Search your images</Link>
          <Row href="/images/all" title="All images" description={images ? `${images.total} images` : 'Your image library'} />
          <Row href="/clusters" title="Clusters" description={clusters ? `${clusters.total} groups found by similarity` : 'Groups found by similarity'} />
          <Row href="/folders" title="Folders" description={folders ? `${folders.total} folders you made` : 'Folders you made'} />
          <h2 className="pb-2 pt-6 text-sm text-muted-foreground">Clusters</h2>
          {loadingClusters && <p role="status">Loading clusters…</p>}
          {clusterError && <p>Could not load clusters. <Link href="/clusters" className="underline">Open Clusters</Link></p>}
          {clusters?.items.length === 0 && <p className="text-sm text-muted-foreground">Your clusters will appear here.</p>}
          {clusters?.items.map(cluster => (
            <article key={cluster.id} className="mb-3 overflow-hidden rounded-lg border border-border">
              <Link href={`/clusters/${cluster.id}`} className="flex min-h-11 items-center justify-between gap-2 px-3 py-2 font-medium">
                {clusterTitle(cluster)}<span className="text-sm text-muted-foreground">{cluster.size}</span>
              </Link>
              <div className="flex gap-1 overflow-x-auto p-2">
                {cluster.preview_images?.map(image => (
                  <Link key={image.id} href={`/clusters/${cluster.id}`} className="h-24 w-24 shrink-0">
                    <LibraryImage src={image.thumbnail_url} alt="Cluster preview" className="h-full w-full rounded object-cover" />
                  </Link>
                ))}
              </div>
            </article>
          ))}
          <Link href="/upload" className="mt-5 flex min-h-12 items-center justify-center rounded-lg border border-border">Upload photos</Link>
        </>
      )}
      {kind === 'studio' && (
        <>
          <h2 className="pt-2 text-sm text-muted-foreground">Make</h2>
          <Row href="/generate" title="Create" description="Start from a description" />
          <h2 className="pt-6 text-sm text-muted-foreground">Change an image</h2>
          <Row href="/edit?job=describe" title="Describe the change" description="Tell the model what should change" />
          <Row href="/edit?job=paint" title="Paint an area" description="Brush over what should change" />
          <Row href="/edit?job=objects" title="Arrange objects" description="Place, move or remove with boxes" />
          <Row href="/edit?job=subject" title="Keep a subject" description="Same subject across new images" />
          <h2 className="pt-6 text-sm text-muted-foreground">Understand and train</h2>
          <Row href="/vision" title="Vision" description="Ask about an image" />
          <Row href="/models" title="My models" description="Your trained models" />
          <h2 className="pb-3 pt-6 text-sm text-muted-foreground">Recent</h2>
          {loadingImages && <p role="status">Loading recent images…</p>}
          {images?.items.length === 0 && <p className="text-sm text-muted-foreground">Your creations will appear here.</p>}
          <div className="flex gap-2 overflow-x-auto">
            {images?.items.map(image => (
              <Link key={image.id} href="/images/all?source=generated" className="h-20 w-20 shrink-0" aria-label="View recent creations">
                <LibraryThumbnail image={image} alt="Recent creation" className="h-full w-full rounded object-cover" />
              </Link>
            ))}
          </div>
        </>
      )}
      {kind === 'account' && (
        <>
          <Row href="/billing" title="Billing" />
          <Row href="/jobs" title="Jobs and activity" />
          <Row href="/notifications" title="Notifications" />
          <Row href="/settings" title="Settings" />
          {user?.role === 'admin' && <Row href="/admin" title="Admin" />}
          {user?.role === 'admin' && <Row href="/debug" title="Debug" />}
          <label className="flex min-h-16 items-center justify-between gap-4">
            Theme
            <select value={theme} onChange={event => setTheme(event.target.value as 'auto' | 'light' | 'dark')} className="rounded border border-border px-3 text-base">
              <option value="auto">Auto</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
          <button onClick={() => { logout(); router.replace('/login'); }} className="mt-4 min-h-12 w-full rounded-lg border border-border">Sign out</button>
        </>
      )}
    </div>
  );
}
