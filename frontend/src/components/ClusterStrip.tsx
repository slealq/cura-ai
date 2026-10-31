'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import type { Cluster } from '@/types';
import { cn } from '@/lib/utils';
import LibraryImage from './LibraryImage';
import { clusterTitle, clusterBullets } from './ClusterTools';

export default function ClusterStrip({ cluster, selected, onSelect }: { cluster: Cluster; selected: boolean; onSelect: () => void }) {
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(700);
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => { setWidth(entry.contentRect.width); setMobile(window.innerWidth < 768); });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const previews = cluster.preview_images || [];
  let sum = 0;
  const images = previews.filter(image => {
    if (!mobile && sum >= width / 138) return false;
    sum += (image.width || 1) / (image.height || 1);
    return true;
  });
  const height = mobile ? 138 : Math.min(180, (width - Math.max(images.length - 1, 0) * 2) / Math.max(sum, 1));
  const href = `/clusters/${cluster.id}`;
  const firstBullet = clusterBullets(cluster)[0];
  const summary = firstBullet?.match(/^.*?[.!?](?=\s|$)/)?.[0] || firstBullet;
  return <article onClick={e => { if (!(e.target as HTMLElement).closest('a, button')) router.push(href); }} className={cn('group relative grid min-w-0 gap-3.5 border-b border-border py-3 md:grid-cols-[230px_minmax(0,1fr)]', selected && 'bg-selection-soft')}>
    <Link href={href} className="min-w-0 pl-14 md:pl-8">
      <h2 className="text-sm font-semibold leading-snug">{clusterTitle(cluster)}</h2>
      {cluster.is_pinned && <span className="text-[11px] font-medium text-muted-foreground">Pinned</span>}
      <p className="mt-1 line-clamp-3 text-[12.5px] text-muted-foreground">{summary || 'Summarizing cluster…'}</p>
      <div className="mt-1.5 flex flex-wrap gap-1">{cluster.common_tags.slice(0, 3).map(tag => <span key={tag} className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{tag}</span>)}</div>
    </Link>
    <button aria-label={`${selected ? 'Deselect' : 'Select'} ${clusterTitle(cluster)}`} aria-pressed={selected} onClick={onSelect} className={cn('absolute left-1 top-4 grid h-[22px] w-[22px] place-items-center rounded-full border border-input focus-visible:ring-2 focus-visible:ring-ring', selected && 'border-selection bg-selection text-primary-foreground')}>
      {selected && <Check className="h-3 w-3" />}
    </button>
    <div ref={ref} className="relative min-w-0 self-center overflow-hidden rounded-md bg-muted">
      <Link href={href} tabIndex={-1} aria-hidden="true" className="flex w-full gap-0.5 overflow-x-auto" style={{ height }}>
        {images.map(image => <LibraryImage key={image.id} src={image.thumbnail_url} alt="" loading="lazy" className="h-full shrink-0 object-contain" style={{ width: height * (image.width || 1) / (image.height || 1), flexGrow: mobile ? 0 : 1 }} />)}
        {!images.length && <span className="m-auto text-xs text-muted-foreground">Previews are being prepared</span>}
      </Link>
      <span className="pointer-events-none absolute bottom-0 right-0 rounded-tl-md bg-primary px-2 py-1 font-mono text-[11px] text-primary-foreground">{cluster.size.toLocaleString()} images</span>
    </div>
  </article>;
}
