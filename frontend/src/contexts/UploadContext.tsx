'use client';

import { createContext, useContext, useState, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { imagesApi } from '@/lib/api';
import { trackFunnelStep } from '@/lib/observability';
import type { BatchUploadResponse } from '@/types';

interface UploadState {
  isUploading: boolean;
  progress: { uploaded: number; total: number } | null;
}

interface UploadContextValue {
  state: UploadState;
  startUpload: (files: File[], folderId?: number, newFolderName?: string) => void;
}

const UploadContext = createContext<UploadContextValue | undefined>(undefined);

const TOAST_ID = 'global-upload';

export function UploadProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<UploadState>({ isUploading: false, progress: null });
  const queryClient = useQueryClient();
  const router = useRouter();
  // Guard against concurrent calls
  const uploadingRef = useRef(false);

  const startUpload = useCallback(
    (files: File[], folderId?: number, newFolderName?: string) => {
      if (uploadingRef.current) return;
      uploadingRef.current = true;
      setState({ isUploading: true, progress: { uploaded: 0, total: files.length } });
      const uploadStart = Date.now();

      trackFunnelStep('upload', 'upload_started', { fileCount: files.length });
      toast.loading(`Uploading 0/${files.length} files...`, { id: TOAST_ID, duration: Infinity });

      (async () => {
        try {
          // Folder creation and assignment are handled by the backend
          // when the ingest job completes — no eager folder creation here
          const data: BatchUploadResponse = await imagesApi.uploadChunked(
            files,
            folderId,
            (uploaded, total) => {
              setState({ isUploading: true, progress: { uploaded, total } });
              const pct = Math.round((uploaded / total) * 100);
              toast.loading(`Sending ${uploaded}/${total} files (${pct}%)...`, { id: TOAST_ID, duration: Infinity });
            },
            newFolderName,
          );

          const count = data.uploaded.length;
          const failCount = data.failed.length;
          const durationMs = Date.now() - uploadStart;

          trackFunnelStep('upload', 'upload_complete', {
            succeeded: count,
            failed: failCount,
            durationMs,
          });

          if (count > 0) {
            toast.success(
              `${count} image${count !== 1 ? 's' : ''} sent — processing in background${failCount > 0 ? ` (${failCount} failed)` : ''}`,
              {
                id: TOAST_ID,
                action: { label: 'View Jobs', onClick: () => router.push('/jobs') },
              },
            );
          } else if (failCount > 0) {
            toast.error(`All ${failCount} uploads failed`, { id: TOAST_ID });
          }

          queryClient.invalidateQueries({ queryKey: ['images'] });
          queryClient.invalidateQueries({ queryKey: ['unfiled-images'] });
          queryClient.invalidateQueries({ queryKey: ['all-images'] });
          queryClient.invalidateQueries({ queryKey: ['stats'] });
          queryClient.invalidateQueries({ queryKey: ['jobs'] });
        } catch (err) {
          const error = err as Error & { partialResult?: BatchUploadResponse };
          if (error.partialResult) {
            const { uploaded, failed } = error.partialResult;
            toast.error(
              `Upload interrupted: ${uploaded.length} succeeded, ${failed.length} failed. ${error.message}`,
              { id: TOAST_ID },
            );
            queryClient.invalidateQueries({ queryKey: ['images'] });
            queryClient.invalidateQueries({ queryKey: ['unfiled-images'] });
            queryClient.invalidateQueries({ queryKey: ['all-images'] });
            queryClient.invalidateQueries({ queryKey: ['jobs'] });
            queryClient.invalidateQueries({ queryKey: ['stats'] });
          } else {
            toast.error(`Upload failed: ${error.message}`, { id: TOAST_ID });
          }
        } finally {
          uploadingRef.current = false;
          setState({ isUploading: false, progress: null });
        }
      })();
    },
    [queryClient, router],
  );

  return (
    <UploadContext.Provider value={{ state, startUpload }}>
      {children}
    </UploadContext.Provider>
  );
}

export function useUpload() {
  const context = useContext(UploadContext);
  if (context === undefined) {
    throw new Error('useUpload must be used within an UploadProvider');
  }
  return context;
}
