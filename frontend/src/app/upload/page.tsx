'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useDropzone } from 'react-dropzone';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Upload, X, Check, AlertCircle, Loader2, ArrowRight } from 'lucide-react';
import { toast } from 'sonner';
import { imagesApi, foldersApi } from '@/lib/api';
import { cn, formatFileSize } from '@/lib/utils';
import type { BatchUploadResponse } from '@/types';

interface FileWithPreview extends File {
  preview?: string;
}

export default function UploadPage() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [files, setFiles] = useState<FileWithPreview[]>([]);
  const [selectedFolderId, setSelectedFolderId] = useState<number | undefined>();
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [uploadProgress, setUploadProgress] = useState<{ uploaded: number; total: number } | null>(null);

  const { data: folders } = useQuery({
    queryKey: ['folders'],
    queryFn: () => foldersApi.list({ limit: 200 }),
  });

  const uploadMutation = useMutation({
    mutationFn: async (filesToUpload: File[]) => {
      let folderId = selectedFolderId;

      // Create a new folder first if needed
      if (showNewFolder && newFolderName.trim()) {
        const folder = await foldersApi.create({ name: newFolderName.trim() });
        folderId = folder.id;
      }

      setUploadProgress({ uploaded: 0, total: filesToUpload.length });
      return imagesApi.uploadChunked(filesToUpload, folderId, (uploaded, total) => {
        setUploadProgress({ uploaded, total });
      });
    },
    onSuccess: (data) => {
      setUploadProgress(null);
      const count = data.uploaded.length;
      const failCount = data.failed.length;
      if (count > 0) {
        toast.success(`${count} image${count !== 1 ? 's' : ''} sent — processing in background${failCount > 0 ? ` (${failCount} failed)` : ''}`, {
          action: { label: 'View Jobs', onClick: () => router.push('/jobs') },
        });
      }
      if (failCount > 0 && count === 0) {
        toast.error(`All ${failCount} uploads failed`);
      }
      if (data.folder_error) {
        toast.error('Images uploaded but failed to add to folder. You can add them from the folder page.');
      }
      queryClient.invalidateQueries({ queryKey: ['images'] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      setFiles([]);
      setNewFolderName('');
      setShowNewFolder(false);
    },
    onError: (error: Error & { partialResult?: BatchUploadResponse }) => {
      setUploadProgress(null);
      if (error.partialResult) {
        const { uploaded, failed } = error.partialResult;
        toast.error(
          `Upload interrupted: ${uploaded.length} succeeded, ${failed.length} failed. ${error.message}`,
        );
        queryClient.invalidateQueries({ queryKey: ['images'] });
        queryClient.invalidateQueries({ queryKey: ['jobs'] });
        queryClient.invalidateQueries({ queryKey: ['stats'] });
      } else {
        toast.error(`Upload failed: ${error.message}`);
      }
      setFiles([]);
    },
  });

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles = acceptedFiles.map((file) =>
      Object.assign(file, {
        preview: URL.createObjectURL(file),
      })
    );
    setFiles((prev) => [...prev, ...newFiles]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'image/*': ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'],
    },
  });

  const removeFile = (index: number) => {
    setFiles((prev) => {
      const file = prev[index];
      if (file.preview) {
        URL.revokeObjectURL(file.preview);
      }
      return prev.filter((_, i) => i !== index);
    });
  };

  const handleUpload = () => {
    if (files.length > 0) {
      uploadMutation.mutate(files);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Upload Images</h1>
        <p className="text-muted-foreground mt-1">
          Upload design inspiration images to process and cluster
        </p>
      </div>

      {/* Folder selector */}
      <div>
        <label className="block text-sm font-medium mb-1">
          Upload to Folder <span className="text-muted-foreground">(optional)</span>
        </label>
        {!showNewFolder ? (
          <div className="flex items-center gap-2">
            <select
              className="flex-1 px-3 py-2 border border-border rounded-lg text-sm"
              value={selectedFolderId ?? ''}
              onChange={(e) => setSelectedFolderId(Number(e.target.value) || undefined)}
            >
              <option value="">No folder (upload to library only)</option>
              {folders?.items.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} ({f.image_count} images)
                </option>
              ))}
            </select>
            <button
              onClick={() => {
                setShowNewFolder(true);
                setSelectedFolderId(undefined);
              }}
              className="px-3 py-2 text-sm text-primary hover:underline shrink-0"
            >
              + New folder
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="New folder name"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              className="flex-1 px-3 py-2 border border-border rounded-lg text-sm"
              autoFocus
            />
            <button
              onClick={() => {
                setShowNewFolder(false);
                setNewFolderName('');
              }}
              className="px-3 py-2 text-sm text-muted-foreground hover:underline shrink-0"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={cn(
          'border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors',
          isDragActive
            ? 'border-primary bg-primary/5'
            : 'border-border hover:border-primary/50 hover:bg-muted/50'
        )}
      >
        <input {...getInputProps()} />
        <Upload className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
        {isDragActive ? (
          <p className="text-lg font-medium">Drop the images here</p>
        ) : (
          <>
            <p className="text-lg font-medium">
              Drag & drop images here, or click to select
            </p>
            <p className="text-sm text-muted-foreground mt-2">
              Supports PNG, JPG, GIF, WebP, BMP
            </p>
          </>
        )}
      </div>

      {/* File List */}
      {files.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">{files.length} files selected</h2>
            <button
              onClick={() => setFiles([])}
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Clear all
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {files.map((file, index) => (
              <div
                key={`${file.name}-${index}`}
                className="relative group bg-muted rounded-lg overflow-hidden"
              >
                {file.preview && (
                  <img
                    src={file.preview}
                    alt={file.name}
                    className="w-full aspect-square object-cover"
                  />
                )}
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors" />
                <button
                  onClick={() => removeFile(index)}
                  className="absolute top-2 right-2 p-1 bg-white/90 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X className="h-4 w-4" />
                </button>
                <div className="absolute bottom-0 left-0 right-0 p-2 bg-gradient-to-t from-black/80 to-transparent">
                  <p className="text-white text-xs truncate">{file.name}</p>
                  <p className="text-white/70 text-xs">
                    {formatFileSize(file.size)}
                  </p>
                </div>
              </div>
            ))}
          </div>

          <button
            onClick={handleUpload}
            disabled={uploadMutation.isPending}
            className={cn(
              'w-full py-3 rounded-lg font-medium transition-colors',
              'bg-primary text-primary-foreground hover:bg-primary/90',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {uploadMutation.isPending ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 className="h-5 w-5 animate-spin" />
                Uploading...
              </span>
            ) : (
              `Upload ${files.length} ${files.length === 1 ? 'Image' : 'Images'}`
            )}
          </button>

          {/* Progress bar */}
          {uploadProgress && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">
                  Sending {uploadProgress.uploaded} / {uploadProgress.total} files...
                </span>
                <span className="font-medium">
                  {Math.round((uploadProgress.uploaded / uploadProgress.total) * 100)}%
                </span>
              </div>
              <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full transition-all duration-300"
                  style={{ width: `${(uploadProgress.uploaded / uploadProgress.total) * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Upload Results */}
      {uploadMutation.isSuccess && (
        <div className="bg-green-50 border border-green-200 dark:bg-green-900/30 dark:border-green-800 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <Check className="h-5 w-5 text-green-600 dark:text-green-400 mt-0.5" />
            <div className="flex-1">
              <h3 className="font-medium text-green-800 dark:text-green-300">Files Sent</h3>
              <p className="text-sm text-green-700 dark:text-green-400 mt-1">
                {uploadMutation.data.uploaded.length} images accepted. Thumbnails and metadata
                are being generated in the background.
              </p>
              {uploadMutation.data.failed.length > 0 && (
                <p className="text-sm text-red-600 dark:text-red-400 mt-1">
                  {uploadMutation.data.failed.length} images failed to upload.
                </p>
              )}
              <div className="flex gap-3 mt-3">
                <button
                  onClick={() => router.push('/images')}
                  className="inline-flex items-center gap-1 text-sm font-medium text-green-700 dark:text-green-300 hover:underline"
                >
                  View Images <ArrowRight className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={() => router.push('/jobs')}
                  className="inline-flex items-center gap-1 text-sm font-medium text-green-700 dark:text-green-300 hover:underline"
                >
                  Monitor Progress <ArrowRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {uploadMutation.isError && (
        <div className="bg-red-50 border border-red-200 dark:bg-red-900/30 dark:border-red-800 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400 mt-0.5" />
            <div>
              <h3 className="font-medium text-red-800 dark:text-red-300">Upload Failed</h3>
              <p className="text-sm text-red-700 dark:text-red-400 mt-1">
                Something went wrong. Please try again.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
