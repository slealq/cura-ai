'use client';

import { useEffect, useRef, useState, type ImgHTMLAttributes } from 'react';
import type { Image } from '@/types';
import { imagesApi } from '@/lib/api';
import LibraryImage from './LibraryImage';

/** Thumbnail sizes bound the longest edge, rather than just the width. */
export default function LibraryThumbnail({ image, ...props }: Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'> & { image: Image }) {
  const host = useRef<HTMLSpanElement>(null);
  const [pixels, setPixels] = useState(0);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const measure = () => {
      const box = element.getBoundingClientRect();
      const ratio = image.width && image.height ? image.width / image.height : 1;
      // Account for object-cover cropping as well as natural-ratio tiles.
      setPixels(Math.max(box.width, box.height, box.width / ratio, box.height * ratio) * window.devicePixelRatio);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    window.addEventListener('resize', measure);
    measure();
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); };
  }, [image.width, image.height]);
  const variants = [
    { size: 200, url: image.thumbnail_urls?.['200'], uri: image.thumbnail_uri_small },
    { size: 400, url: image.thumbnail_urls?.['400'], uri: image.thumbnail_uri_medium },
    { size: 800, url: image.thumbnail_urls?.['800'], uri: image.thumbnail_uri_large },
  ].filter(v => v.url || v.uri);
  const chosen = variants.find(v => v.size >= pixels) || variants[variants.length - 1];
  const src = chosen?.url || (chosen?.uri ? imagesApi.getThumbnailUrl(chosen.uri.split('/').pop()!) : image.thumbnail_url);
  return <span ref={host} className="block h-full w-full">
    {pixels > 0 && src && <LibraryImage {...props} src={src} />}
  </span>;
}
