'use client';

import LibraryImage from '@/components/LibraryImage';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, ExternalLink, RefreshCw, FolderOpen, Zap, ChevronDown, ChevronUp, Clock } from 'lucide-react';
import { toast } from 'sonner';
import Link from 'next/link';
import type { Image } from '@/types';
import { imagesApi, jobsApi, settingsApi, billingApi, generationApi, editApi } from '@/lib/api';
import { STATUS_RANK } from '@/lib/pipeline';
import { cn, formatDate, formatDateCompact, formatFileSize } from '@/lib/utils';
import ImageCard from './ImageCard';
import ModelSelector from './ModelSelector';
import PipelineProgress from './PipelineProgress';
import { useModelCatalog } from '@/hooks/useModelCatalog';
import { Slider } from './Slider';
import { thumbnail, type InspectorTool } from './Inspector';

interface ImageDrawerProps {
  image: Image;
  onClose: () => void;
  images?: Image[];
  onNavigate?: (image: Image) => void;
  onTool?: (tool: InspectorTool, image: Image) => void;
}

export default function ImageDrawer({ image, onClose, images, onNavigate, onTool }: ImageDrawerProps) {
  const [tab, setTab] = useState('Details');
  const [mobileDetails, setMobileDetails] = useState(false);
  const touchStart = useRef({ x: 0, y: 0 });
  const index = images?.findIndex((i) => i.id === image.id) ?? -1;
  const navigate = useCallback(
    (delta: number) => {
      if (index < 0) return;
      const next = images?.[index + delta];
      if (next && onNavigate) onNavigate(next);
    },
    [images, index, onNavigate]
  );
  const { data: generation } = useQuery({
    queryKey: ['viewer-generation', image.generated_image_id],
    queryFn: () =>
      image.source === 'edited'
        ? editApi.getImage(image.generated_image_id!)
        : generationApi.getImage(image.generated_image_id!),
    enabled: !!image.generated_image_id,
  });
  const { data: catalog } = useModelCatalog();
  const VISION_MODELS = (catalog?.language ?? []).map((m) => ({
    value: m.id,
    label: m.label,
    provider: 'fal',
  }));
  const queryClient = useQueryClient();
  const hasInitModel = useRef(false);
  const [showDescribeDialog, setShowDescribeDialog] = useState(false);
  const [descriptionPrompt, setDescriptionPrompt] = useState('');
  const [tagPrompt, setTagPrompt] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [staleSteps, setStaleSteps] = useState<string[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [temperature, setTemperature] = useState<number | null>(null);
  const [maxTokensTag, setMaxTokensTag] = useState<number | null>(null);
  const [maxTokensDescribe, setMaxTokensDescribe] = useState<number | null>(null);

  const isViewer = !!images;
  const viewerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!isViewer) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    viewerRef.current?.querySelector<HTMLButtonElement>('[data-viewer-close]')?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
      previousFocus?.focus();
    };
  }, [isViewer]);
  useEffect(() => {
    if (!isViewer) return;
    const key = (e: KeyboardEvent) => {
      if (showDescribeDialog) return;
      if (e.key === 'Tab') {
        const controls = Array.from(
          viewerRef.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href], input, textarea, select'
          ) ?? []
        ).filter((element) => element.getClientRects().length > 0);
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
      if ((e.target as HTMLElement).matches('input, textarea, select')) return;
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        navigate(-1);
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        navigate(1);
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [isViewer, navigate, showDescribeDialog]);

  // Live image data — polls every 3s while processing
  const { data: liveImage } = useQuery({
    queryKey: ['images', image.id],
    queryFn: () => imagesApi.get(image.id),
    refetchInterval: isProcessing ? 3000 : false,
    initialData: image,
  });

  // Active jobs for this image — polls while processing
  const { data: imageJobs } = useQuery({
    queryKey: ['jobs', 'image', image.id],
    queryFn: () => jobsApi.listByImage(image.id),
    refetchInterval: isProcessing ? 3000 : false,
    enabled: isProcessing || liveImage.status === 'failed',
  });

  const { data: batches } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => jobsApi.list({ limit: 50 }),
    enabled: showDescribeDialog,
    refetchInterval: showDescribeDialog ? 5000 : false,
  });
  const batchRunning =
    batches?.items.some(
      (job) =>
        ['batch_reprocess', 'batch_describe'].includes(job.job_type) &&
        ['running', 'pending'].includes(job.status)
    ) ?? false;

  // Detect completion from job polling
  useEffect(() => {
    if (!isProcessing || !imageJobs) return;

    const activeJobs = imageJobs.items.filter((j) => j.status === 'pending' || j.status === 'running');

    if (activeJobs.length === 0 && imageJobs.items.length > 0) {
      const failedJobs = imageJobs.items.filter((j) => j.status === 'failed');
      if (failedJobs.length > 0) {
        toast.error('Processing failed', {
          description: failedJobs[0].error_message || 'An error occurred',
        });
      } else {
        toast.success('Processing complete');
      }
      setIsProcessing(false);
      setStaleSteps([]);
      queryClient.invalidateQueries({ queryKey: ['images'] });
      queryClient.invalidateQueries({ queryKey: ['images', image.id] });
    }
  }, [imageJobs, isProcessing, image.id, queryClient]);

  const { data: similarImages } = useQuery({
    queryKey: ['similar-images', image.id],
    queryFn: () => imagesApi.getSimilar(image.id, 6),
    enabled: liveImage.status === 'embedded' || liveImage.status === 'clustered',
  });

  const { data: imageFolders } = useQuery({
    queryKey: ['image-folders', image.id],
    queryFn: () => imagesApi.getFolders(image.id),
  });

  const { data: defaultPrompts } = useQuery({
    queryKey: ['prompt-settings'],
    queryFn: settingsApi.getPrompts,
  });

  const { data: presets } = useQuery({
    queryKey: ['presets'],
    queryFn: settingsApi.listPresets,
  });

  // Provider config for settings-driven model default
  const { data: providerConfig } = useQuery({
    queryKey: ['provider-config'],
    queryFn: settingsApi.getProviderConfig,
  });

  // Vision costs — use actual image dimensions for accurate estimate
  const { data: visionCosts } = useQuery({
    queryKey: ['vision-costs', image.id, image.width, image.height],
    queryFn: () =>
      image.width && image.height
        ? billingApi.getVisionCostsEstimate({ width: image.width, height: image.height })
        : billingApi.getVisionCosts(),
  });

  // Per-image processing costs — only fetch when drawer is open and image has been processed
  const hasProcessing =
    liveImage.metadata?.tagging_model ||
    liveImage.metadata?.caption_model ||
    liveImage.metadata?.embedding_model;
  const { data: processingCosts } = useQuery({
    queryKey: ['processing-costs', image.id],
    queryFn: () => imagesApi.getProcessingCosts(image.id),
    enabled: !!hasProcessing,
    staleTime: 60_000,
  });

  // Initialize selectedModel from provider config
  useEffect(() => {
    if (providerConfig && catalog && !hasInitModel.current) {
      hasInitModel.current = true;
      const modelId = providerConfig.fal_vision_model;
      setSelectedModel(
        catalog?.language.some((m) => m.id === modelId) ? modelId : (catalog?.defaults.vision_model ?? '')
      );
    }
  }, [providerConfig, catalog]);

  const reprocessMutation = useMutation({
    mutationFn: (options: {
      tag_prompt?: string;
      description_prompt?: string;
      provider?: string;
      model?: string;
      temperature?: number;
      max_tokens_tag?: number;
      max_tokens_describe?: number;
    }) => imagesApi.reprocess(image.id, options),
    onSuccess: (data) => {
      toast.success('Describe started', {
        description: `Job #${data.job_id}`,
        action: {
          label: 'View Jobs',
          onClick: () => {
            window.location.href = '/jobs';
          },
        },
      });
      setIsProcessing(true);
      setStaleSteps([]);
      setShowDescribeDialog(false);
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: () => toast.error('Failed to start describe'),
  });

  // Initialize prompts from defaults when dialog opens
  const initPrompts = useCallback(() => {
    if (defaultPrompts) {
      setDescriptionPrompt(defaultPrompts.description_prompt);
      setTagPrompt(defaultPrompts.tag_prompt);
    }
    // Reset model to configured default
    if (providerConfig) {
      const modelId = providerConfig.fal_vision_model;
      setSelectedModel(
        catalog?.language.some((m) => m.id === modelId) ? modelId : (catalog?.defaults.vision_model ?? '')
      );
      // Init advanced params from settings
      setTemperature(providerConfig.vision_temperature ?? 1.0);
      setMaxTokensTag(providerConfig.max_tokens_tagging ?? 1000);
      setMaxTokensDescribe(providerConfig.max_tokens_description ?? 3000);
    }
    setShowAdvanced(false);
  }, [defaultPrompts, providerConfig, catalog]);

  useEffect(() => {
    if (showDescribeDialog) {
      initPrompts();
    }
  }, [showDescribeDialog, initPrompts]);

  // Close on escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showDescribeDialog) setShowDescribeDialog(false);
        else onClose();
      }
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose, showDescribeDialog]);

  const getModelParams = () => {
    const m = VISION_MODELS.find((v) => v.value === selectedModel);
    return {
      provider: m?.provider,
      model: selectedModel,
    };
  };

  // Compute cost for describe (tag + describe + embed)
  const getDescribeCost = (): number | null => {
    if (!visionCosts || !selectedModel) return null;
    const m = VISION_MODELS.find((v) => v.value === selectedModel);
    if (!m?.provider) return null;
    const provCosts = visionCosts.costs[m.provider];
    if (!provCosts) return null;
    const modelCosts = provCosts[selectedModel];
    if (!modelCosts) return null;
    return modelCosts.total || (modelCosts.tag || 0) + (modelCosts.describe || 0);
  };
  const describeCost = getDescribeCost();

  const handleDescribeSubmit = () => {
    setShowDescribeDialog(false);
    reprocessMutation.mutate({
      description_prompt: descriptionPrompt || undefined,
      tag_prompt: tagPrompt || undefined,
      ...getModelParams(),
      temperature: temperature ?? undefined,
      max_tokens_tag: maxTokensTag ?? undefined,
      max_tokens_describe: maxTokensDescribe ?? undefined,
    });
  };

  const download = async () => {
    const notice = toast.loading('Preparing download');
    try {
      const response = await fetch(imagesApi.getImageUrl(liveImage.object_key));
      if (!response.ok) throw new Error('Download request failed');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = liveImage.original_filename || `image-${liveImage.id}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.dismiss(notice);
    } catch {
      toast.error('Could not download image. Try opening the original.', { id: notice });
    }
  };

  const imageUrl = liveImage.image_url || imagesApi.getImageUrl(liveImage.object_key);
  const tags = liveImage.metadata?.tags || [];

  return (
    <div className="contents">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />

      {/* Drawer */}
      <div
        ref={viewerRef}
        onTouchStart={e => { touchStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }; }}
        onTouchEnd={e => {
          if (window.innerWidth >= 768 || (e.target as HTMLElement).closest('[data-viewer-info]')) return;
          const dx = e.changedTouches[0].clientX - touchStart.current.x;
          const dy = e.changedTouches[0].clientY - touchStart.current.y;
          if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy)) navigate(dx < 0 ? 1 : -1);
          else if (dy > 90 && Math.abs(dy) > Math.abs(dx)) onClose();
        }}

        role={images ? 'dialog' : undefined}
        aria-modal={images ? true : undefined}
        aria-label={images ? 'Image viewer' : undefined}
        className={
          images
            ? 'image-viewer fixed inset-0 z-50 flex bg-background'
            : 'fixed inset-y-0 right-0 w-full max-w-xl bg-card shadow-xl z-50 overflow-y-auto'
        }
      >
        {images && (
          <div className="relative flex min-w-0 flex-1 flex-col viewer-canvas bg-chrome p-4">
            <div className="relative min-h-0 flex-1">
              <LibraryImage
                src={imageUrl}
                alt={image.original_filename || ''}
                className="absolute inset-0 h-full w-full object-contain"
              />
            </div>
            <div className="flex items-center justify-center gap-2 pt-3">
              <button
                aria-label="Previous image"
                disabled={index <= 0}
                onClick={() => navigate(-1)}
                className="p-2 disabled:opacity-30"
              >
                ←
              </button>
              {images.slice(Math.max(0, index - 4), Math.max(0, index - 4) + 9).map((item) => (
                <button
                  key={item.id}
                  aria-label={`View image ${item.id}`}
                  onClick={() => onNavigate?.(item)}
                  className={cn(
                    'rounded border-2',
                    item.id === image.id ? 'border-selection' : 'border-transparent'
                  )}
                >
                  <LibraryImage src={thumbnail(item)} alt="" className="h-12 w-12 rounded object-cover" />
                </button>
              ))}
              <button
                aria-label="Next image"
                disabled={index < 0 || index >= images.length - 1}
                onClick={() => navigate(1)}
                className="p-2 disabled:opacity-30"
              >
                →
              </button>
            </div>
          </div>
        )}
        {images && <div className="viewer-mobile-controls hidden max-md:flex absolute inset-x-0 top-0 z-10 items-center justify-between p-3">
          <button aria-label="Close image" onClick={onClose} className="rounded-full bg-background p-3"><X /></button>
          <button onClick={() => setMobileDetails(true)} className="rounded-full bg-background px-4 py-3">Details / Tags / Description</button>
        </div>}
        <div
          data-viewer-info
          data-open={mobileDetails}
          className={
            images ? 'viewer-info flex w-[380px] max-w-full shrink-0 flex-col border-l border-border max-md:w-full' : ''
          }
        >
          {images && <button className="hidden max-md:block border-b border-border p-2" onClick={() => setMobileDetails(false)}>Close details</button>}
          {/* Header */}
          <div className="sticky top-0 bg-card border-b border-border px-6 py-4 flex items-center justify-between">
            <h2 className="font-semibold truncate">{liveImage.original_filename || liveImage.object_key}</h2>
            <button
              data-viewer-close
              aria-label="Close viewer"
              onClick={onClose}
              className="p-2 hover:bg-muted rounded-lg transition-colors"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {images && (
            <div className="flex items-center justify-between border-b border-border px-4 py-2 text-sm md:hidden">
              <button aria-label="Previous image" disabled={index <= 0} onClick={() => navigate(-1)}>
                ← Previous
              </button>
              <span>{index >= 0 ? `${index + 1} / ${images.length}` : 'Linked image'}</span>
              <button
                aria-label="Next image"
                disabled={index < 0 || index >= images.length - 1}
                onClick={() => navigate(1)}
              >
                Next →
              </button>
            </div>
          )}
          {images && (
            <div role="tablist" aria-label="Image information" className="flex border-b border-border">
              {['Details', 'Tags', 'Description'].map((name) => (
                <button
                  key={name}
                  role="tab"
                  aria-selected={tab === name}
                  onClick={() => setTab(name)}
                  className={cn('flex-1 p-3 text-sm', tab === name && 'border-b-2 border-selection')}
                >
                  {name}
                </button>
              ))}
            </div>
          )}
          <div className="p-6 space-y-6 overflow-y-auto flex-1">
            {(!images || tab === 'Details') && (
              <>
                {generation && (
                  <div className="space-y-2 text-sm">
                    <h3 className="font-medium">Generation</h3>
                    <p>{generation.base_model}</p>
                    <p className="whitespace-pre-wrap">{generation.prompt}</p>
                    {generation.lora_model_id && (
                      <p>LoRA: {generation.lora_model_name || `#${generation.lora_model_id}`}</p>
                    )}
                  </div>
                )}
                {images && (
                  <div className="grid grid-cols-5 gap-1">
                    {['ingested', 'tagged', 'described', 'embedded', 'clustered'].map((step) => {
                      const current = STATUS_RANK[liveImage.status] ?? -1;
                      return (
                        <div key={step} title={step} className="text-[9px] text-muted-foreground">
                          <div
                            className={cn(
                              'mb-1 h-1 rounded',
                              liveImage.status === 'failed'
                                ? 'bg-danger'
                                : current >= (STATUS_RANK[step] ?? 100)
                                  ? 'bg-success'
                                  : 'bg-muted'
                            )}
                          />
                          {step}
                        </div>
                      );
                    })}
                  </div>
                )}
                {liveImage.status === 'failed' && (
                  <p className="text-sm text-danger">
                    {liveImage.error_message ||
                      imageJobs?.items.find((job) => job.status === 'failed')?.error_message ||
                      'Processing failed. See Jobs for error details.'}
                  </p>
                )}
                {/* Image */}
                <div className={cn('rounded-lg overflow-hidden bg-muted', images && 'md:hidden')}>
                  <LibraryImage src={imageUrl} alt={liveImage.original_filename || ''} className="w-full h-auto" />
                </div>

                {/* Pipeline Status */}
                {!images && (
                  <PipelineProgress status={liveImage.status} variant="full" staleSteps={staleSteps} />
                )}

                {/* Actions */}
                <div className="flex items-center gap-2 flex-wrap">
                  <a
                    href={imageUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-2 hover:bg-muted rounded-lg transition-colors"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
                  <button
                    onClick={() => setShowDescribeDialog(true)}
                    disabled={isProcessing}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
                  >
                    <RefreshCw className={cn('h-4 w-4', isProcessing && 'animate-spin')} />
                    {isProcessing ? 'Processing...' : 'Describe'}
                  </button>
                </div>

                {/* Folders */}
                {imageFolders && imageFolders.length > 0 && (
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground mb-2">Folders</h3>
                    <div className="flex flex-wrap gap-1">
                      {imageFolders.map((f) => (
                        <Link
                          key={f.id}
                          href={`/images/folder/${f.id}`}
                          onClick={onClose}
                          className="inline-flex items-center gap-1 px-2 py-0.5 bg-muted rounded-full text-xs hover:bg-muted/80 transition-colors"
                        >
                          <FolderOpen className="h-3 w-3" />
                          {f.name}
                        </Link>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
            {(!images || tab === 'Description') && (
              <>
                {/* Description */}
                {!liveImage.metadata?.description_long && (
                  <p className="text-sm text-muted-foreground">No description yet.</p>
                )}
                {liveImage.metadata?.description_long && (
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground mb-1">Description</h3>
                    <div className="text-sm whitespace-pre-line">{liveImage.metadata.description_long}</div>
                  </div>
                )}
              </>
            )}
            {(!images || tab === 'Tags') && (
              <>
                {/* Tags */}
                {!tags.length && (
                  <p className="text-sm text-muted-foreground">
                    No tags yet. Describe this image to add tags.
                  </p>
                )}
                {tags.length > 0 && (
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground mb-2">Tags</h3>
                    <div className="flex flex-wrap gap-1">
                      {tags.map((tag) => (
                        <span key={tag} className="px-2 py-0.5 bg-muted rounded-full text-xs">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
            {(!images || tab === 'Details') && (
              <>
                {/* Metadata */}
                <div>
                  <h3 className="text-sm font-medium text-muted-foreground mb-2">Details</h3>
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    <dt className="text-muted-foreground">Dimensions</dt>
                    <dd>
                      {liveImage.width && liveImage.height
                        ? `${liveImage.width} × ${liveImage.height}`
                        : 'N/A'}
                    </dd>
                    <dt className="text-muted-foreground">File Size</dt>
                    <dd>{formatFileSize(liveImage.file_size)}</dd>
                    <dt className="text-muted-foreground">Source</dt>
                    <dd className="capitalize">{liveImage.source.replace('_', ' ')}</dd>
                    <dt className="text-muted-foreground">Ingested</dt>
                    <dd>{formatDate(liveImage.ingested_at)}</dd>
                    <dt className="text-muted-foreground">Created</dt>
                    <dd>{formatDate(liveImage.created_at)}</dd>
                  </dl>
                </div>

                {/* Processing Info */}
                {hasProcessing && (
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground mb-2">Processing Info</h3>
                    <div className="rounded-lg border border-border overflow-hidden">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-border bg-muted/50">
                            <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Step</th>
                            <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Model</th>
                            <th className="text-right px-3 py-1.5 font-medium text-muted-foreground">Time</th>
                            <th className="text-right px-3 py-1.5 font-medium text-muted-foreground">Cost</th>
                          </tr>
                        </thead>
                        <tbody>
                          {liveImage.metadata?.tagging_model && (
                            <tr className="border-b border-border/50">
                              <td className="px-3 py-1.5">Tag</td>
                              <td className="px-3 py-1.5 font-mono text-muted-foreground">
                                {liveImage.metadata.tagging_model}
                              </td>
                              <td className="px-3 py-1.5 text-right text-muted-foreground">
                                {liveImage.metadata.tagging_duration_ms != null
                                  ? `${(liveImage.metadata.tagging_duration_ms / 1000).toFixed(1)}s`
                                  : '-'}
                              </td>
                              <td className="px-3 py-1.5 text-right">
                                {processingCosts?.operations.find((o) => o.operation === 'tag') ? (
                                  <span className="inline-flex items-center gap-0.5 text-warning">
                                    <Zap className="h-3 w-3" />
                                    {processingCosts.operations
                                      .find((o) => o.operation === 'tag')!
                                      .sparks.toFixed(2)}
                                  </span>
                                ) : (
                                  <span className="text-muted-foreground">-</span>
                                )}
                              </td>
                            </tr>
                          )}
                          {liveImage.metadata?.caption_model && (
                            <tr className="border-b border-border/50">
                              <td className="px-3 py-1.5">Describe</td>
                              <td className="px-3 py-1.5 font-mono text-muted-foreground">
                                {liveImage.metadata.caption_model}
                              </td>
                              <td className="px-3 py-1.5 text-right text-muted-foreground">
                                {liveImage.metadata.caption_duration_ms != null
                                  ? `${(liveImage.metadata.caption_duration_ms / 1000).toFixed(1)}s`
                                  : '-'}
                              </td>
                              <td className="px-3 py-1.5 text-right">
                                {processingCosts?.operations.find((o) => o.operation === 'describe') ? (
                                  <span className="inline-flex items-center gap-0.5 text-warning">
                                    <Zap className="h-3 w-3" />
                                    {processingCosts.operations
                                      .find((o) => o.operation === 'describe')!
                                      .sparks.toFixed(2)}
                                  </span>
                                ) : (
                                  <span className="text-muted-foreground">-</span>
                                )}
                              </td>
                            </tr>
                          )}
                          {liveImage.metadata?.embedding_model && (
                            <tr className="border-b border-border/50">
                              <td className="px-3 py-1.5">Embed</td>
                              <td className="px-3 py-1.5 font-mono text-muted-foreground">
                                {liveImage.metadata.embedding_model}
                              </td>
                              <td className="px-3 py-1.5 text-right text-muted-foreground">
                                {liveImage.metadata.embedding_duration_ms != null
                                  ? `${(liveImage.metadata.embedding_duration_ms / 1000).toFixed(1)}s`
                                  : '-'}
                              </td>
                              <td className="px-3 py-1.5 text-right">
                                {processingCosts?.operations.find((o) => o.operation === 'embed') ? (
                                  <span className="inline-flex items-center gap-0.5 text-warning">
                                    <Zap className="h-3 w-3" />
                                    {processingCosts.operations
                                      .find((o) => o.operation === 'embed')!
                                      .sparks.toFixed(2)}
                                  </span>
                                ) : (
                                  <span className="text-muted-foreground">-</span>
                                )}
                              </td>
                            </tr>
                          )}
                        </tbody>
                        {processingCosts && processingCosts.total_sparks > 0 && (
                          <tfoot>
                            <tr className="bg-muted/30">
                              <td colSpan={3} className="px-3 py-1.5 text-right font-medium">
                                Total
                              </td>
                              <td className="px-3 py-1.5 text-right">
                                <span className="inline-flex items-center gap-0.5 font-medium text-warning">
                                  <Zap className="h-3 w-3" />
                                  {processingCosts.total_sparks.toFixed(2)}
                                </span>
                              </td>
                            </tr>
                          </tfoot>
                        )}
                      </table>
                    </div>
                    {/* Processed timestamp */}
                    {(liveImage.metadata?.embedded_at ||
                      liveImage.metadata?.described_at ||
                      liveImage.metadata?.tagged_at) && (
                      <p className="text-xs text-muted-foreground mt-1.5 flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        Processed{' '}
                        {formatDateCompact(
                          liveImage.metadata.embedded_at ||
                            liveImage.metadata.described_at ||
                            liveImage.metadata.tagged_at
                        )}
                      </p>
                    )}
                  </div>
                )}

                {/* Similar Images */}
                {similarImages && similarImages.length > 0 && (
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground mb-2">Similar Images</h3>
                    <div className="grid grid-cols-3 gap-2">
                      {similarImages.map((img) =>
                        images && onNavigate ? (
                          <button
                            key={img.id}
                            aria-label={`View similar image ${img.id}`}
                            onClick={() => onNavigate(img)}
                          >
                            <LibraryImage
                              src={thumbnail(img)}
                              alt={img.original_filename || ''}
                              className="aspect-square w-full rounded object-cover"
                            />
                          </button>
                        ) : (
                          <ImageCard key={img.id} image={img} />
                        )
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
          {images && onTool && (
            <footer className="flex flex-wrap gap-2 border-t border-border bg-background p-3">
              {(['Edit', 'Describe', 'Ask Vision', 'Add to folder', 'Delete'] as InspectorTool[]).map(
                (tool) => (
                  <button
                    key={tool}
                    onClick={() => onTool(tool, liveImage)}
                    className={cn(
                      'rounded border border-border px-2 py-1.5 text-xs hover:bg-accent',
                      tool === 'Delete' && 'text-danger'
                    )}
                  >
                    {tool === 'Ask Vision' ? 'Ask' : tool}
                  </button>
                )
              )}
              <button
                onClick={() => void download()}
                className="rounded border border-border px-2 py-1.5 text-xs"
              >
                Download
              </button>
            </footer>
          )}
        </div>
      </div>

      {/* Describe Dialog */}
      {showDescribeDialog && (
        <>
          <div className="fixed inset-0 bg-black/50 z-50" onClick={() => setShowDescribeDialog(false)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="mobile-modal bg-card rounded-xl shadow-xl max-w-2xl w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold">Describe Image</h3>
              {batchRunning && <p className="text-sm text-warning">A describe batch is already running.</p>}
              <p className="text-sm text-muted-foreground">
                Tag, describe, and embed this image using the selected vision model.
              </p>

              {presets && presets.length > 0 && (
                <div>
                  <label className="block text-sm font-medium mb-1">Preset</label>
                  <select
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                    value=""
                    onChange={(e) => {
                      const p = presets.find((pr) => pr.id === Number(e.target.value));
                      if (p) {
                        setTagPrompt(p.tag_prompt);
                        setDescriptionPrompt(p.description_prompt);
                      }
                    }}
                  >
                    <option value="" disabled>
                      Load from preset...
                    </option>
                    {presets.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                        {p.is_default ? ' (active)' : ''}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <ModelSelector
                label="Model"
                models={VISION_MODELS}
                value={selectedModel}
                onChange={(v) => setSelectedModel(v)}
                size="sm"
              />

              <div>
                <label className="block text-sm font-medium mb-2">Tag Instructions</label>
                <textarea
                  value={tagPrompt}
                  onChange={(e) => setTagPrompt(e.target.value)}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm font-mono resize-y min-h-[120px]"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">Description Instructions</label>
                <textarea
                  value={descriptionPrompt}
                  onChange={(e) => setDescriptionPrompt(e.target.value)}
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm font-mono resize-y min-h-[120px]"
                />
              </div>

              {/* Advanced Parameters */}
              <button
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                Advanced Parameters
              </button>

              {showAdvanced && (
                <div className="border border-border rounded-lg p-4 space-y-3">
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">
                      Temperature: {(temperature ?? 1.0).toFixed(1)}
                    </label>
                    <Slider
                      min={0}
                      max={20}
                      value={Math.round((temperature ?? 1.0) * 10)}
                      onChange={(v) => setTemperature(v / 10)}
                      className="w-full"
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                      <span>0.0</span>
                      <span>2.0</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">
                        Tag Tokens: {maxTokensTag ?? 1000}
                      </label>
                      <Slider
                        min={100}
                        max={4000}
                        step={100}
                        value={maxTokensTag ?? 1000}
                        onChange={(v) => setMaxTokensTag(v)}
                        className="w-full"
                      />
                      <div className="flex justify-between text-[10px] text-muted-foreground">
                        <span>100</span>
                        <span>4000</span>
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">
                        Description Tokens: {maxTokensDescribe ?? 3000}
                      </label>
                      <Slider
                        min={500}
                        max={8000}
                        step={100}
                        value={maxTokensDescribe ?? 3000}
                        onChange={(v) => setMaxTokensDescribe(v)}
                        className="w-full"
                      />
                      <div className="flex justify-between text-[10px] text-muted-foreground">
                        <span>500</span>
                        <span>8000</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div className="flex items-center gap-2 justify-end">
                {describeCost !== null && describeCost > 0 && (
                  <span className="inline-flex items-center gap-0.5 text-xs text-warning mr-auto">
                    <Zap className="h-3 w-3" />~{Math.round(describeCost)} sparks
                  </span>
                )}
                <button
                  onClick={() => setShowDescribeDialog(false)}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDescribeSubmit}
                  disabled={reprocessMutation.isPending || !catalog || !selectedModel || batchRunning}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {reprocessMutation.isPending ? 'Starting...' : 'Describe'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
