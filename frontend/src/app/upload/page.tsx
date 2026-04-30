'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useDropzone } from 'react-dropzone';
import { useQuery } from '@tanstack/react-query';
import { Upload, X, Loader2, Info } from 'lucide-react';
import { foldersApi } from '@/lib/api';
import { cn, formatFileSize } from '@/lib/utils';
import { useUpload } from '@/contexts/UploadContext';
import { trackFunnelStep } from '@/lib/observability';

interface FileWithPreview extends File {
  preview?: string;
}

export default function UploadPage() {
  const router = useRouter();
  const { startUpload, state } = useUpload();
  const [files, setFiles] = useState<FileWithPreview[]>([]);
  const [selectedFolderId, setSelectedFolderId] = useState<number | undefined>();
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');

  const { data: folders } = useQuery({
    queryKey: ['folders'],
    queryFn: () => foldersApi.list({ limit: 200 }),
  });

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles = acceptedFiles.map((file) =>
      Object.assign(file, {
        preview: URL.createObjectURL(file),
      })
    );
    setFiles((prev) => [...prev, ...newFiles]);
    trackFunnelStep('upload', 'files_selected', { count: acceptedFiles.length });
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
    if (files.length === 0) return;
    startUpload(files, selectedFolderId, showNewFolder ? newFolderName : undefined);
    setFiles([]);
    setNewFolderName('');
    setShowNewFolder(false);
    router.push('/images');
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Upload Images</h1>
        <p className="text-muted-foreground mt-1">
          Upload design inspiration images to process and cluster
        </p>
      </div>

      {/* Upload in progress banner */}
      {state.isUploading && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-blue-50 border border-blue-200 dark:bg-blue-900/30 dark:border-blue-800 text-sm text-blue-800 dark:text-blue-300">
          <Info className="h-4 w-4 shrink-0" />
          <span>
            An upload is already in progress
            {state.progress && ` (${state.progress.uploaded}/${state.progress.total} files)`}.
            Check the notification toast for status.
          </span>
        </div>
      )}

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
            disabled={state.isUploading}
            className={cn(
              'w-full py-3 rounded-lg font-medium transition-colors',
              'bg-primary text-primary-foreground hover:bg-primary/90',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {state.isUploading ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 className="h-5 w-5 animate-spin" />
                Upload in progress...
              </span>
            ) : (
              `Upload ${files.length} ${files.length === 1 ? 'Image' : 'Images'}`
            )}
          </button>
        </div>
      )}
    </div>
  );
}
