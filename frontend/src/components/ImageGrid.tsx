'use client';

import LibraryThumbnail from '@/components/LibraryThumbnail';

import Link from 'next/link';
import { Suspense, useState, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { useDeletingImages } from '@/lib/deletingImages';
import { useQuery, useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, useRouter, usePathname } from 'next/navigation';
import { Check, FileText, FolderMinus, FolderPlus, Loader2, RefreshCw, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { imagesApi, jobsApi } from '@/lib/api';
import ImageDrawer from '@/components/ImageDrawer';
import Inspector, { type InspectorTool } from '@/components/Inspector';
import DescribeAllDialog from '@/components/DescribeAllDialog';
import { cn } from '@/lib/utils';
import type { Image, ImageListResponse } from '@/types';

type SourceKey = 'upload' | 'generated' | 'edited';
type Density = 'S' | 'M' | 'L';

const SOURCE_FILTERS: { key: SourceKey | null; label: string }[] = [
  { key: null, label: 'All' },
  { key: 'upload', label: 'Uploads' },
  { key: 'generated', label: 'Generated' },
  { key: 'edited', label: 'Edited' },
];

const COLUMN_WIDTH: Record<Density, number> = { S: 150, M: 210, L: 300 };
const DENSITY_KEY = 'library-density';
const PAGE_SIZE = 60;
const NOT_DESCRIBED = new Set(['ingested', 'normalized', 'tagged']);

interface FetchParams {
  status?: string;
  min_status?: string;
  max_status?: string;
  source?: string;
  in_folder?: boolean;
  skip?: number;
  limit?: number;
}

interface ImageGridProps {
  title: string;
  queryKeyPrefix: string;
  fetchImages: (params: FetchParams) => Promise<ImageListResponse>;
  folderId?: number;
  clusterId?: number;
  inspectorOverview?: ReactNode;
  /** Show the All / Uploads / Generated / Edited filter (needs `source` support in fetchImages). */
  showSourceFilter?: boolean;
  /** Extra controls rendered next to the title, e.g. folder actions. */
  headerActions?: React.ReactNode;
  /** Rendered between the title row and the toolbar, e.g. a folder description. */
  subtitle?: React.ReactNode;
}

export default function ImageGrid(props: ImageGridProps) {
  return (
    <Suspense
      fallback={
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <ImageGridContent {...props} />
    </Suspense>
  );
}

function Segmented<T extends string | null>({
  options,
  value,
  onChange,
  label,
}: {
  options: { key: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex gap-0.5 rounded-lg bg-muted p-0.5">
      {options.map((o) => (
        <button
          key={o.label}
          onClick={() => onChange(o.key)}
          aria-pressed={value === o.key}
          className={cn(
            'h-7 whitespace-nowrap rounded-md px-2.5 text-[12.5px] font-medium transition-colors',
            value === o.key
              ? 'bg-background text-foreground shadow-sm dark:bg-accent'
              : 'text-muted-foreground hover:text-foreground'
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Tile({
  image,
  selected,
  selecting,
  onOpen,
  onToggle,
}: {
  image: Image;
  selected: boolean;
  selecting: boolean;
  onOpen: () => void;
  onToggle: () => void;
}) {
  const thumb = image.thumbnail_uri_medium || image.thumbnail_uri_small;
  const src = image.thumbnail_url || (thumb ? imagesApi.getThumbnailUrl(thumb.split('/').pop()!) : null);
  const ratio = image.width && image.height ? image.width / image.height : 1;
  const flag =
    image.status === 'failed'
      ? { text: 'Failed', cls: 'text-danger' }
      : image.status === 'pending'
        ? { text: 'Processing', cls: 'text-muted-foreground' }
        : NOT_DESCRIBED.has(image.status)
          ? { text: 'Not described', cls: 'text-warning' }
          : null;
  const description = image.metadata?.description_long;
  const tags = image.metadata?.tags?.slice(0, 4) ?? [];

  return (
    <div
      data-selecting={selecting}
      className={cn(
        'library-tile group relative h-full overflow-hidden rounded-md bg-muted',
        selected && 'outline outline-[3px] -outline-offset-[3px] outline-selection'
      )}
    >
      <button
        type="button"
        onClick={(e) => (selecting || e.metaKey || e.ctrlKey || e.shiftKey ? onToggle() : onOpen())}
        className="block h-full w-full"
        aria-label={`${image.original_filename || `Image ${image.id}`}${selected ? ', selected' : ''}`}
      >
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <LibraryThumbnail
            image={image}
            alt=""
            loading="lazy"
            style={{ aspectRatio: ratio }}
            className={cn(
              'block h-full w-full object-cover transition-transform duration-200',
              selected && 'scale-[0.94] rounded'
            )}
          />
        ) : (
          <div
            style={{ aspectRatio: ratio }}
            className="grid h-full w-full place-items-center text-xs text-muted-foreground"
          >
            No preview
          </div>
        )}
      </button>
      <button
        type="button"
        onClick={onToggle}
        aria-label={selected ? 'Deselect' : 'Select'}
        aria-pressed={selected}
        className={cn(
          'tile-select absolute left-2 top-2 grid h-[22px] w-[22px] place-items-center rounded-full border-[1.5px] text-white transition-opacity',
          selected ? 'border-selection bg-selection opacity-100' : 'border-white/95 bg-black/20',
          !selected &&
            (selecting ? 'opacity-100' : 'opacity-0 focus-visible:opacity-100 group-hover:opacity-100')
        )}
      >
        <Check className={cn('h-3 w-3', selected ? 'opacity-100' : 'opacity-0')} strokeWidth={3} />
      </button>
      {(image.source === 'generated' || image.source === 'edited') && (
        <span className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/45 px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider text-white backdrop-blur">
          {image.source}
        </span>
      )}
      {(description || tags.length > 0) && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 hidden bg-gradient-to-t from-black/85 via-black/60 to-transparent px-2.5 pb-2.5 pt-8 text-white opacity-0 transition-opacity group-hover:opacity-100 md:block">
          {description && <p className="line-clamp-3 text-xs leading-snug">{description}</p>}
          {tags.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1 overflow-hidden">
              {tags.map((tag) => (
                <span key={tag} className="max-w-full truncate rounded bg-white/20 px-1.5 py-0.5 text-[10.5px]">
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {flag && (
        <span
          className={cn(
            'pointer-events-none absolute right-2 top-2 rounded bg-background px-1.5 py-0.5 text-[10.5px] font-medium',
            flag.cls
          )}
        >
          {flag.text}
        </span>
      )}
    </div>
  );
}

// Keep assignments and ratios for the current result sequence. Appending a page only
// adds to the shortest column; existing DOM nodes and reserved heights stay put.
function AppendOnlyGrid({ images, density, children }: {
  images: Image[];
  density: Density;
  children: (image: Image) => ReactNode;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const layout = useRef<{ count: number; density: Density; ids: number[]; columns: number[]; ratios: number[] }>({
    count: 0, density, ids: [], columns: [], ratios: [],
  });
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const [phone, setPhone] = useState(false);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 767px)');
    const update = () => setPhone(media.matches);
    update(); media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  const count = phone ? ({ S: 3, M: 2, L: 1 }[density]) : Math.max(1, Math.floor((width + 8) / (COLUMN_WIDTH[density] + 8)));
  const tileWidth = (width - (count - 1) * 8) / count;
  let current = layout.current;
  if (current.count !== count || current.density !== density ||
      current.ids.length > images.length || current.ids.some((id, i) => images[i]?.id !== id)) {
    current = { count, density, ids: [], columns: [], ratios: [] };
    layout.current = current;
  }
  const heights = Array<number>(count).fill(0);
  current.columns.forEach((column, i) => { heights[column] += tileWidth / current.ratios[i] + 8; });
  for (let i = current.ids.length; i < images.length; i++) {
    const image = images[i];
    const ratio = image.width && image.height ? image.width / image.height : 1;
    const column = heights.indexOf(Math.min(...heights));
    current.ids.push(image.id);
    current.columns.push(column);
    current.ratios.push(ratio);
    heights[column] += tileWidth / ratio + 8;
  }
  return (
    <div ref={container} className="pb-24">
      {width > 0 && (
        <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` }}>
          {Array.from({ length: count }, (_, column) => (
            <div key={column} className="min-w-0">
              {images.map((image, i) => current.columns[i] === column ? (
                <div key={image.id} style={{ aspectRatio: current.ratios[i] }} className="mb-2 overflow-hidden rounded-md">
                  {children(image)}
                </div>
              ) : null)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ImageGridContent({
  title,
  queryKeyPrefix,
  fetchImages,
  folderId,
  clusterId,
  inspectorOverview,
  showSourceFilter = false,
  headerActions,
  subtitle,
}: ImageGridProps) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const imageIdParam = searchParams.get('image_id');
  const entryTool = searchParams.get('tool');
  const entryHint = searchParams.get('hint');
  const sourceParam = searchParams.get('source') as SourceKey | null;
  const source = showSourceFilter && SOURCE_FILTERS.some((s) => s.key === sourceParam) ? sourceParam : null;

  const [inspectorHidden, setInspectorHidden] = useState(false);
  const [wide, setWide] = useState(false);
  const [mobileInspector, setMobileInspector] = useState(false);
  const [tool, setTool] = useState<InspectorTool | null>(null);
  const [toolImages, setToolImages] = useState<Image[] | null>(null);
  useEffect(() => {
    try {
      setInspectorHidden(localStorage.getItem('library-inspector-hidden') === 'true');
    } catch {}
    const media = window.matchMedia('(min-width: 1100px)');
    const update = () => setWide(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    if (!['Create', 'Edit', 'Ask Vision'].includes(entryTool || '')) {
      setTool(null);
      return;
    }
    setTool(entryTool as InspectorTool);
    setToolImages(null);
    setMobileInspector(true);
  }, [entryTool]);

  const inspectorVisible = wide && !inspectorHidden;
  const [openImage, setOpenImage] = useState<Image | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [density, setDensity] = useState<Density>('M');
  const [showDescribeAll, setShowDescribeAll] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(DENSITY_KEY) as Density | null;
      if (saved && saved in COLUMN_WIDTH) setDensity(saved);
    } catch {
      // keep default
    }
  }, []);

  const changeDensity = (d: Density) => {
    setDensity(d);
    try {
      localStorage.setItem(DENSITY_KEY, d);
    } catch {
      // ignore
    }
  };

  const changeSource = (s: SourceKey | null) => {
    const next = new URLSearchParams(searchParams.toString());
    if (s) next.set('source', s);
    else next.delete('source');
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname);
    setSelectedIds(new Set());
  };

  // Auto-open viewer when image_id is in URL params
  const hasOpenedLinked = useRef<number | null>(null);
  const { data: linkedImage } = useQuery({
    queryKey: ['images', Number(imageIdParam)],
    queryFn: () => imagesApi.get(Number(imageIdParam)),
    enabled: !!imageIdParam,
  });
  useEffect(() => {
    if (linkedImage && linkedImage.id !== hasOpenedLinked.current) {
      hasOpenedLinked.current = linkedImage.id;
      setOpenImage(linkedImage);
    }
  }, [linkedImage]);
  useEffect(() => {
    if (!imageIdParam) hasOpenedLinked.current = null;
  }, [imageIdParam]);

  const { data, isLoading, isError, error, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: [queryKeyPrefix, source],
      queryFn: ({ pageParam }) =>
        fetchImages({ ...(source ? { source } : {}), skip: pageParam, limit: PAGE_SIZE }),
      initialPageParam: 0,
      getNextPageParam: (last, pages) => {
        const loaded = pages.reduce((n, p) => n + p.items.length, 0);
        return loaded < last.total && last.items.length > 0 ? loaded : undefined;
      },
    });

  const deleting = useDeletingImages();
  const images = useMemo(
    () => (data?.pages.flatMap((p) => p.items) ?? []).filter((image) => !deleting.has(image.id)),
    [data, deleting]
  );
  const total = data?.pages[0]?.total ?? 0;

  // Load the next page when the sentinel scrolls into view
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !isFetchingNextPage) fetchNextPage();
      },
      { rootMargin: '600px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const { data: jobs } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => jobsApi.list({ limit: 50 }),
    refetchInterval: 5000,
  });
  const hasBatchRunning =
    jobs?.items.some(
      (j) =>
        (j.job_type === 'batch_reprocess' || j.job_type === 'batch_describe') &&
        (j.status === 'running' || j.status === 'pending')
    ) ?? false;

  const clearSelection = () => {
    setSelectedIds(new Set());
    setSelectMode(false);
    setToolImages(null);
  };

  const toggle = (id: number) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const allLoadedSelected = images.length > 0 && images.every((img) => selectedIds.has(img.id));
  const selecting = selectMode || selectedIds.size > 0;

  useEffect(() => {
    if (!selecting) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !tool && !openImage) clearSelection();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [selecting, openImage, tool]);

  const dockButton =
    'flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-medium text-primary-foreground/90 transition-colors hover:bg-primary-foreground/10 hover:text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <div className="flex items-start gap-5">
      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="flex items-baseline gap-2 text-xl font-semibold tracking-tight">
            {title}
            <span className="font-mono text-[13px] font-normal tabular-nums text-muted-foreground">
              {total}
            </span>
          </h1>
          <button
            aria-pressed={inspectorVisible}
            onClick={() => {
              const hidden = !inspectorHidden;
              setInspectorHidden(hidden);
              try {
                localStorage.setItem('library-inspector-hidden', String(hidden));
              } catch {}
            }}
            className="rounded-md border border-border px-2 py-1 text-xs min-[1100px]:block hidden"
          >
            {inspectorVisible ? 'Hide inspector' : 'Show inspector'}
          </button>
          {headerActions && (
            <div className="ml-auto flex flex-wrap items-center gap-1.5">{headerActions}</div>
          )}
        </div>
        {!inspectorVisible && (
          <button
            onClick={() => {
              setMobileInspector(true);
              setTool('Create');
            }}
            className="rounded-md border border-border px-3 py-1.5 text-sm"
          >
            Create
          </button>
        )}
        {subtitle}
        {(entryHint === 'edit' || entryHint === 'vision') && (
          <div className="flex items-start gap-3 rounded-lg border border-selection/20 bg-selection-soft p-3 text-sm">
            <p className="flex-1">Select images, then choose {entryHint === 'edit' ? 'Edit' : 'Ask Vision'} in the inspector or More tools. <Link className="underline" href={`/${entryHint === 'edit' ? 'edit' : 'vision'}?advanced=1`}>{entryHint === 'edit' ? 'Upload sources or use advanced editing' : 'Upload a file or view analysis history'}</Link></p>
            <button aria-label="Dismiss hint" onClick={() => {
              const next = new URLSearchParams(searchParams.toString());
              next.delete('hint');
              router.replace(next.size ? `${pathname}?${next}` : pathname, { scroll: false });
            }} className="rounded p-1 hover:bg-accent"><X className="h-4 w-4" /></button>
          </div>
        )}

        <div className="library-filters flex flex-wrap items-center gap-2">
          <button className="hidden max-md:block rounded-md border border-border px-3 text-sm" aria-pressed={selectMode} onClick={() => { setSelectMode(!selectMode); setSelectedIds(new Set()); }}>{selectMode ? 'Done' : 'Select'}</button>
          {showSourceFilter && (
            <Segmented label="Source" options={SOURCE_FILTERS} value={source} onChange={changeSource} />
          )}
          <div className="ml-auto flex items-center gap-1.5">
            {folderId && (
              <button
                onClick={() => setShowDescribeAll(true)}
                disabled={hasBatchRunning}
                title={
                  hasBatchRunning
                    ? 'A describe job is already running'
                    : 'Describe every image in this folder'
                }
                className="flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                <FileText className="h-3.5 w-3.5" />
                Describe all
              </button>
            )}
            {images.length > 0 && (
              <button
                onClick={() =>
                  allLoadedSelected ? clearSelection() : setSelectedIds(new Set(images.map((i) => i.id)))
                }
                className="h-7 rounded-md px-2.5 text-[12.5px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                {allLoadedSelected ? 'Deselect all' : 'Select all'}
              </button>
            )}
            <Segmented
              label="Thumbnail size"
              options={(['S', 'M', 'L'] as Density[]).map((d) => ({ key: d, label: d }))}
              value={density}
              onChange={changeDensity}
            />
          </div>
        </div>

        {isLoading ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : isError ? (
          <div className="flex h-64 flex-col items-center justify-center gap-2 text-center">
            <p className="font-medium">Couldn&apos;t load these images</p>
            <p className="max-w-md text-sm text-muted-foreground">{error?.message}</p>
            <button
              onClick={() => refetch()}
              className="mt-1 rounded-md border border-input px-3 py-1.5 text-[13px] font-medium hover:bg-accent"
            >
              Try again
            </button>
          </div>
        ) : images.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-1 text-center">
            <p className="font-medium">No images here</p>
            <p className="text-sm text-muted-foreground">
              {source
                ? 'Nothing matches this filter. Try a different source.'
                : 'Upload images or create some to start your library.'}
            </p>
          </div>
        ) : (
          <>
            <AppendOnlyGrid images={images} density={density}>
              {(image) => (
                <Tile
                  key={image.id}
                  image={image}
                  selected={selectedIds.has(image.id)}
                  selecting={selecting}
                  onOpen={() => setOpenImage(image)}
                  onToggle={() => toggle(image.id)}
                />
              )}
            </AppendOnlyGrid>
            <div ref={sentinelRef} className="flex h-10 items-center justify-center">
              {isFetchingNextPage && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
            </div>
          </>
        )}

        {/* Compact fallback when the inspector is hidden. */}
        {selecting && !inspectorVisible && (
          <div
            role="toolbar"
            aria-label="Selection actions"
            className="selection-actions fixed bottom-5 left-1/2 z-40 flex max-w-[calc(100vw-24px)] -translate-x-1/2 overflow-x-auto items-center gap-0.5 whitespace-nowrap rounded-xl bg-primary p-1.5 text-primary-foreground shadow-[0_18px_40px_-12px_rgb(0_0_0/0.45)]"
          >
            <button onClick={clearSelection} className={cn(dockButton, 'px-2')} aria-label="Clear selection">
              <X className="h-4 w-4" />
            </button>
            <span className="px-1.5 text-[13px] font-semibold tabular-nums">{selectedIds.size} selected</span>
            <span className="mx-1 h-5 w-px bg-primary-foreground/20" />
            <button
              onClick={() => setTool('Describe')}
              disabled={hasBatchRunning}
              title={
                hasBatchRunning ? 'A describe job is already running' : 'Tag, describe and embed these images'
              }
              className={dockButton}
            >
              <RefreshCw className="h-4 w-4" />
              Describe
            </button>
            <button onClick={() => setTool('Add to folder')} className={dockButton}>
              <FolderPlus className="h-4 w-4" />
              Add to folder
            </button>
            {folderId && (
              <button onClick={() => setTool('Remove from folder')} className={dockButton}>
                <FolderMinus className="h-4 w-4" />
                Remove from folder
              </button>
            )}
            <button
              className={dockButton}
              onClick={() => {
                setToolImages(Array.from(selectedIds).map(id => images.find(image => image.id === id)).filter((image): image is Image => !!image));
                setMobileInspector(true);
              }}
            >
              More tools
            </button>
            <span className="mx-1 h-5 w-px bg-primary-foreground/20" />
            <button onClick={() => setTool('Delete')} className={dockButton}>
              <Trash2 className="h-4 w-4" />
              Delete
            </button>
          </div>
        )}

        {showDescribeAll && folderId && (
          <DescribeAllDialog
            folderId={folderId}
            imageCount={total}
            onClose={() => setShowDescribeAll(false)}
            onStarted={(jobId, count) => {
              setShowDescribeAll(false);
              toast.success(`Describing ${count} images`, {
                description: `Job #${jobId}`,
                action: { label: 'View Jobs', onClick: () => router.push('/jobs') },
              });
              queryClient.invalidateQueries({ queryKey: ['jobs'] });
              queryClient.invalidateQueries({ queryKey: [queryKeyPrefix] });
            }}
          />
        )}

        {openImage && (
          <ImageDrawer
            key={openImage.id}
            image={openImage}
            images={images}
            onNavigate={setOpenImage}
            onTool={(next, image) => {
              if (next === 'Edit') { router.push(`/edit?sources=${image.id}`); return; }
              setSelectedIds(new Set([image.id]));
              setToolImages([image]);
              setTool(next);
              // Explicit tool handoffs can open a temporary inspector without changing the saved preference.
              setMobileInspector(true);
              setOpenImage(null);
            }}
            onClose={() => {
              setOpenImage(null);
              const next = new URLSearchParams(searchParams.toString());
              next.delete('image_id');
              router.replace(next.size ? `${pathname}?${next}` : pathname);
            }}
          />
        )}
      </div>
      {(inspectorVisible || tool || mobileInspector) && (
        <div
          className={cn(
            'library-inspector sticky top-4 h-[calc(100vh-120px)] w-[340px] shrink-0',
            !inspectorVisible && 'fixed inset-0 z-50 h-full w-full bg-background sm:left-auto sm:w-[340px]'
          )}
        >
          <Inspector
            onDismiss={
              !inspectorVisible
                ? () => {
                    setMobileInspector(false);
                    setTool(null);
                    setToolImages(null);
                    const params = new URLSearchParams(searchParams.toString());
                    params.delete('tool');
                    router.replace(params.size ? `${pathname}?${params}` : pathname, { scroll: false });
                  }
                : undefined
            }
            title={title}
            total={total}
            images={toolImages ?? Array.from(selectedIds).map(id => images.find(image => image.id === id)).filter((image): image is Image => !!image)}
            tool={tool}
            onTool={(next) => {
              if (next === 'Edit') {
                const ids = toolImages ? toolImages.map(image => image.id) : Array.from(selectedIds);
                router.push(`/edit?sources=${ids.join(',')}`);
                return;
              }
              setTool(next);
              if (!next) {
                setToolImages(null);
                const params = new URLSearchParams(searchParams.toString());
                params.delete('tool');
                router.replace(params.size ? `${pathname}?${params}` : pathname, { scroll: false });
              }
            }}
            onClear={() => {
              clearSelection();
              setToolImages(null);
            }}
            folderId={folderId}
            clusterId={clusterId}
            overview={inspectorOverview}
            hasBatchRunning={hasBatchRunning}
            onDispatched={() => {
              setMobileInspector(false);
              void queryClient.invalidateQueries({ queryKey: [queryKeyPrefix] });
            }}
          />
        </div>
      )}
    </div>
  );
}
