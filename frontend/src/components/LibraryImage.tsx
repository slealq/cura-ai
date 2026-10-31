'use client';

import { useEffect, useRef, useState, type ImgHTMLAttributes } from 'react';
import { resolveImageUrl } from '@/lib/api';

// JWT rotation must not change the identity of an already loaded image.
function imageKey(src: string) {
  const url = new URL(src, (typeof window === 'undefined' ? 'http://localhost' : window.location.origin));
  url.searchParams.delete('token');
  // Covers returned by list APIs already have SAS URLs. Refresh those through
  // the authenticated serving route if their signature expires before scrolling.
  if (url.hostname.endsWith('.blob.core.windows.net')) {
    const [, , directory, filename] = url.pathname.split('/');
    const prefixes: Record<string, string> = {
      thumbnails: '/api/images/thumbnails', images: '/api/images/files',
      folder_covers: '/api/folders/covers', cluster_covers: '/api/clusters/covers',
      generated_thumbnails: '/api/generation/thumbnails',
    };
    if (prefixes[directory]) return `${prefixes[directory]}/${filename}`;
  }
  return url.toString();
}

function ImageContent({ src, initialSource, loading, ...props }: ImgHTMLAttributes<HTMLImageElement> & { src: string; initialSource: string }) {
  const host = useRef<HTMLImageElement>(null);
  const [visible, setVisible] = useState(loading !== 'lazy');
  const [url, setUrl] = useState<string | undefined>(() => {
    const candidate = new URL(initialSource, typeof window === 'undefined' ? 'http://localhost' : window.location.origin);
    const expiry = candidate.searchParams.get('se');
    return candidate.hostname.endsWith('.blob.core.windows.net') && expiry && Date.parse(expiry) > Date.now() + 60_000
      ? initialSource : undefined;
  });
  const hasInitialUrl = useRef(!!url);
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (visible || !host.current) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) setVisible(true);
    }, { rootMargin: '300px' });
    observer.observe(host.current);
    return () => observer.disconnect();
  }, [visible]);

  useEffect(() => {
    if (!visible || (attempt === 0 && hasInitialUrl.current)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      resolveImageUrl(src, attempt > 0).then((next) => {
        if (active) setUrl(next);
      }).catch(() => {
        if (active) {
          if (attempt < 2) setAttempt(attempt + 1);
          else setFailed(true);
        }
      });
    }, attempt * 700);
    return () => { active = false; window.clearTimeout(timer); };
  }, [src, visible, attempt]);

  // A stalled connection may never emit an error event. Bound that wait too.
  useEffect(() => {
    if (!visible || !url || loaded || failed) return;
    const timer = window.setTimeout(() => {
      setUrl(undefined);
      if (attempt < 2) setAttempt(attempt + 1);
      else setFailed(true);
    }, 20_000);
    return () => window.clearTimeout(timer);
  }, [visible, url, loaded, failed, attempt]);

  return (
    <>
      {failed ? (
        <span role="img" aria-label={props.alt || 'Image unavailable'} className={props.className} style={props.style}>
          <span className="flex h-full min-h-12 items-center justify-center bg-muted text-xs text-muted-foreground">Image unavailable</span>
        </span>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img {...props} ref={host} alt={props.alt || ''} src={url} loading={loading} onLoad={(event) => {
          setLoaded(true);
          props.onLoad?.(event);
        }} onError={(event) => {
          props.onError?.(event);
          setLoaded(false);
          setUrl(undefined);
          if (attempt < 2) setAttempt(attempt + 1);
          else setFailed(true);
        }} />
      )}
    </>
  );
}

export default function LibraryImage(props: ImgHTMLAttributes<HTMLImageElement>) {
  if (!props.src) return null;
  const key = imageKey(props.src);
  return <ImageContent {...props} src={key} initialSource={props.src} key={key} />;
}
