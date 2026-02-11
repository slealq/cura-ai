'use client';

import { useEffect, useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, ExternalLink, RefreshCw, Tag, FileText, Cpu } from 'lucide-react';
import { toast } from 'sonner';
import type { Image } from '@/types';
import { imagesApi, jobsApi, settingsApi } from '@/lib/api';
import { cn, formatDate, formatFileSize } from '@/lib/utils';
import { hasReachedStatus } from '@/lib/pipeline';
import ImageCard from './ImageCard';
import PipelineProgress from './PipelineProgress';

interface ImageDrawerProps {
  image: Image;
  onClose: () => void;
}

export default function ImageDrawer({ image, onClose }: ImageDrawerProps) {
  const queryClient = useQueryClient();
  const [showReprocessDialog, setShowReprocessDialog] = useState(false);
  const [showTagDialog, setShowTagDialog] = useState(false);
  const [showDescribeDialog, setShowDescribeDialog] = useState(false);
  const [descriptionGuidance, setDescriptionGuidance] = useState('');
  const [tagGuidance, setTagGuidance] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [staleSteps, setStaleSteps] = useState<string[]>([]);

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
    enabled: isProcessing,
  });

  // Detect completion from job polling
  useEffect(() => {
    if (!isProcessing || !imageJobs) return;

    const activeJobs = imageJobs.items.filter(
      (j) => j.status === 'pending' || j.status === 'running'
    );

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
    enabled:
      liveImage.status === 'embedded' || liveImage.status === 'clustered',
  });

  const { data: defaultGuidance } = useQuery({
    queryKey: ['guidance-settings'],
    queryFn: settingsApi.getGuidance,
  });

  const tagMutation = useMutation({
    mutationFn: (options?: { tag_guidance?: string }) =>
      imagesApi.tagImage(image.id, options),
    onSuccess: () => {
      toast.info('Tagging started');
      setIsProcessing(true);
      setStaleSteps((prev) =>
        Array.from(new Set([...prev, 'embedded', 'clustered']))
      );
      setShowTagDialog(false);
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });

  const describeMutation = useMutation({
    mutationFn: (options?: { description_guidance?: string }) =>
      imagesApi.describeImage(image.id, options),
    onSuccess: () => {
      toast.info('Describing started');
      setIsProcessing(true);
      setStaleSteps((prev) =>
        Array.from(new Set([...prev, 'embedded', 'clustered']))
      );
      setShowDescribeDialog(false);
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });

  const embedMutation = useMutation({
    mutationFn: () => imagesApi.embedImage(image.id),
    onSuccess: () => {
      toast.info('Embedding started');
      setIsProcessing(true);
      setStaleSteps((prev) =>
        Array.from(new Set([...prev, 'clustered']))
      );
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });

  const reprocessMutation = useMutation({
    mutationFn: (options: {
      tag_guidance?: string;
      description_guidance?: string;
    }) => imagesApi.reprocess(image.id, options),
    onSuccess: () => {
      toast.info('Reprocessing started');
      setIsProcessing(true);
      setStaleSteps([]);
      setShowReprocessDialog(false);
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });

  const canTag =
    liveImage.status === 'failed' ||
    hasReachedStatus(liveImage.status, 'ingested');
  const canDescribe =
    liveImage.status === 'failed' ||
    hasReachedStatus(liveImage.status, 'tagged');
  const canEmbed =
    liveImage.status === 'failed' ||
    hasReachedStatus(liveImage.status, 'described');

  // Initialize guidance from defaults when dialogs open
  const initGuidance = useCallback(() => {
    if (defaultGuidance) {
      setDescriptionGuidance(defaultGuidance.description_guidance || '');
      setTagGuidance(defaultGuidance.tag_guidance || '');
    }
  }, [defaultGuidance]);

  useEffect(() => {
    if (showReprocessDialog || showTagDialog || showDescribeDialog) {
      initGuidance();
    }
  }, [showReprocessDialog, showTagDialog, showDescribeDialog, initGuidance]);

  // Close on escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showReprocessDialog) setShowReprocessDialog(false);
        else if (showTagDialog) setShowTagDialog(false);
        else if (showDescribeDialog) setShowDescribeDialog(false);
        else onClose();
      }
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose, showReprocessDialog, showTagDialog, showDescribeDialog]);

  const handleReprocess = () => {
    reprocessMutation.mutate({
      description_guidance: descriptionGuidance || undefined,
      tag_guidance: tagGuidance || undefined,
    });
  };

  const handleTag = () => {
    tagMutation.mutate({
      tag_guidance: tagGuidance || undefined,
    });
  };

  const handleDescribe = () => {
    describeMutation.mutate({
      description_guidance: descriptionGuidance || undefined,
    });
  };

  const imageUrl = imagesApi.getImageUrl(liveImage.object_key);
  const tags = liveImage.metadata?.tags || [];

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed inset-y-0 right-0 w-full max-w-xl bg-white shadow-xl z-50 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-border px-6 py-4 flex items-center justify-between">
          <h2 className="font-semibold truncate">
            {liveImage.original_filename || liveImage.object_key}
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-muted rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Image */}
          <div className="rounded-lg overflow-hidden bg-muted">
            <img
              src={imageUrl}
              alt={liveImage.original_filename || ''}
              className="w-full h-auto"
            />
          </div>

          {/* Pipeline Status */}
          <PipelineProgress
            status={liveImage.status}
            variant="full"
            staleSteps={staleSteps}
          />

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
            {canTag && (
              <button
                onClick={() => setShowTagDialog(true)}
                disabled={tagMutation.isPending || isProcessing}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
              >
                <Tag className="h-3.5 w-3.5" />
                Tag
              </button>
            )}
            {canDescribe && (
              <button
                onClick={() => setShowDescribeDialog(true)}
                disabled={describeMutation.isPending || isProcessing}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
              >
                <FileText className="h-3.5 w-3.5" />
                Describe
              </button>
            )}
            {canEmbed && (
              <button
                onClick={() => embedMutation.mutate()}
                disabled={embedMutation.isPending || isProcessing}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
              >
                <Cpu className="h-3.5 w-3.5" />
                Embed
              </button>
            )}
            <button
              onClick={() => setShowReprocessDialog(true)}
              disabled={isProcessing}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
            >
              <RefreshCw className={cn('h-4 w-4', isProcessing && 'animate-spin')} />
              {isProcessing ? 'Processing...' : 'Reprocess'}
            </button>
          </div>

          {/* Description */}
          {liveImage.metadata?.description_long && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Description
              </h3>
              <div className="text-sm whitespace-pre-line">
                {liveImage.metadata.description_long}
              </div>
            </div>
          )}

          {/* Tags */}
          {tags.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Tags
              </h3>
              <div className="flex flex-wrap gap-1">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="px-2 py-0.5 bg-muted rounded-full text-xs"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Metadata */}
          <div>
            <h3 className="text-sm font-medium text-muted-foreground mb-2">
              Details
            </h3>
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
              <dd className="capitalize">
                {liveImage.source.replace('_', ' ')}
              </dd>
              <dt className="text-muted-foreground">Ingested</dt>
              <dd>{formatDate(liveImage.ingested_at)}</dd>
            </dl>
          </div>

          {/* Model Info */}
          {liveImage.metadata && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Processing Info
              </h3>
              <dl className="grid grid-cols-2 gap-2 text-xs">
                {liveImage.metadata.tagging_model && (
                  <>
                    <dt className="text-muted-foreground">Tagging Model</dt>
                    <dd className="font-mono">
                      {liveImage.metadata.tagging_model}
                    </dd>
                  </>
                )}
                {liveImage.metadata.caption_model && (
                  <>
                    <dt className="text-muted-foreground">Description Model</dt>
                    <dd className="font-mono">
                      {liveImage.metadata.caption_model}
                    </dd>
                  </>
                )}
                {liveImage.metadata.embedding_model && (
                  <>
                    <dt className="text-muted-foreground">Embedding Model</dt>
                    <dd className="font-mono">
                      {liveImage.metadata.embedding_model}
                    </dd>
                  </>
                )}
              </dl>
            </div>
          )}

          {/* Similar Images */}
          {similarImages && similarImages.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Similar Images
              </h3>
              <div className="grid grid-cols-3 gap-2">
                {similarImages.map((img) => (
                  <ImageCard key={img.id} image={img} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Tag Dialog */}
      {showTagDialog && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => setShowTagDialog(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-white rounded-xl shadow-xl max-w-lg w-full p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold">Tag Image</h3>
              <p className="text-sm text-muted-foreground">
                Optionally provide guidance to influence how this image is
                tagged.
              </p>

              <div>
                <label className="block text-sm font-medium mb-2">
                  Tag Guidance
                </label>
                <textarea
                  value={tagGuidance}
                  onChange={(e) => setTagGuidance(e.target.value)}
                  placeholder="e.g., Focus on architectural elements and materials"
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
                />
              </div>

              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowTagDialog(false)}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleTag}
                  disabled={tagMutation.isPending}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {tagMutation.isPending ? 'Starting...' : 'Tag'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Describe Dialog */}
      {showDescribeDialog && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => setShowDescribeDialog(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-white rounded-xl shadow-xl max-w-lg w-full p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold">Describe Image</h3>
              <p className="text-sm text-muted-foreground">
                Optionally provide guidance to influence how this image is
                described.
              </p>

              <div>
                <label className="block text-sm font-medium mb-2">
                  Description Guidance
                </label>
                <textarea
                  value={descriptionGuidance}
                  onChange={(e) => setDescriptionGuidance(e.target.value)}
                  placeholder="e.g., Focus on detailed physical features and positioning"
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
                />
              </div>

              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowDescribeDialog(false)}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDescribe}
                  disabled={describeMutation.isPending}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {describeMutation.isPending ? 'Starting...' : 'Describe'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Reprocess Dialog */}
      {showReprocessDialog && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => setShowReprocessDialog(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-white rounded-xl shadow-xl max-w-lg w-full p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold">Reprocess Image</h3>
              <p className="text-sm text-muted-foreground">
                Optionally provide guidance to influence how this image is tagged
                and described.
              </p>

              <div>
                <label className="block text-sm font-medium mb-2">
                  Description Guidance
                </label>
                <textarea
                  value={descriptionGuidance}
                  onChange={(e) => setDescriptionGuidance(e.target.value)}
                  placeholder="e.g., Focus on detailed physical features and positioning"
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">
                  Tag Guidance
                </label>
                <textarea
                  value={tagGuidance}
                  onChange={(e) => setTagGuidance(e.target.value)}
                  placeholder="e.g., Focus on architectural elements and materials"
                  className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-y min-h-[80px]"
                />
              </div>

              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowReprocessDialog(false)}
                  className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleReprocess}
                  disabled={reprocessMutation.isPending}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {reprocessMutation.isPending ? 'Starting...' : 'Reprocess'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
