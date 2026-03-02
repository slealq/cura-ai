import axios from 'axios';
import type {
  AdminUserBalance,
  AnomalyListResponse,
  AnomalySummaryResponse,
  APIKeyInfo,
  AuthUser,
  BatchJobImage,
  BatchUploadResponse,
  BillingLogListResponse,
  Cluster,
  ClusterDetail,
  ClusteringConfig,
  ClusterListResponse,
  CostCatalogEntry,
  DecisionListResponse,
  EditConfig,
  EditCosts,
  EvaluationCostsResponse,
  EvaluationListResponse,
  Folder,
  FolderBrief,
  FolderListResponse,
  GeneratedImage,
  GeneratedImageListResponse,
  GenerationConfig,
  GenerationCosts,
  Image,
  ImageListResponse,
  Job,
  JobListResponse,
  LogListResponse,
  LogStats,
  LoraEvaluation,
  LoraListResponse,
  LoraModel,
  MetricsResponse,
  ModelBulkUpdateRequest,
  PipelineStats,
  PlatformUsageSummary,
  ProcessingCostResponse,
  PromptPreset,
  ProviderConfig,
  ProviderModel,
  ReconciliationResponse,
  SearchResponse,
  StepResponse,
  SummarizeCostsResponse,
  TokenResponse,
  TraceResponse,
  TrainingConfig,
  TrainingCosts,
  TransactionListResponse,
  UsageSummary,
  UserBalance,
  VisionCosts,
} from '@/types';

const apiBaseURL = process.env.NEXT_PUBLIC_API_URL
  ? `${process.env.NEXT_PUBLIC_API_URL}/api`
  : '/api';

const api = axios.create({
  baseURL: apiBaseURL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Generate a session_id once per browser session, persist in localStorage
function getSessionId(): string {
  let sid = localStorage.getItem('session_id');
  if (!sid) {
    sid = crypto.randomUUID();
    localStorage.setItem('session_id', sid);
  }
  return sid;
}

// Store the last trace_id from a response for Sentry breadcrumbs
let lastTraceId: string | null = null;
export function getLastTraceId(): string | null {
  return lastTraceId;
}

// Attach Bearer token + correlation headers to all requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // Correlation IDs
  config.headers['X-Session-Id'] = getSessionId();
  if (!config.headers['X-Trace-Id']) {
    config.headers['X-Trace-Id'] = crypto.randomUUID().replace(/-/g, '');
  }
  return config;
});

// Track refresh state to avoid multiple simultaneous refreshes
let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

function onTokenRefreshed(token: string) {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
}

function addRefreshSubscriber(cb: (token: string) => void) {
  refreshSubscribers.push(cb);
}

// Extract meaningful error messages + handle 401 with token refresh
api.interceptors.response.use(
  (response) => {
    // Capture correlation IDs from response headers
    const traceId = response.headers['x-trace-id'];
    if (traceId) lastTraceId = traceId;
    return response;
  },
  async (error) => {
    const originalRequest = error.config;

    // If 401 and not already retrying, try refreshing the token
    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !originalRequest.url?.includes('/auth/')
    ) {
      originalRequest._retry = true;

      if (!isRefreshing) {
        isRefreshing = true;
        const refreshToken = localStorage.getItem('refresh_token');

        if (refreshToken) {
          try {
            const { data } = await axios.post<TokenResponse>(`${apiBaseURL}/auth/refresh`, {
              refresh_token: refreshToken,
            });
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('refresh_token', data.refresh_token);
            isRefreshing = false;
            onTokenRefreshed(data.access_token);

            originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
            return api(originalRequest);
          } catch {
            isRefreshing = false;
            refreshSubscribers = [];
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            window.location.href = '/login';
            return Promise.reject(error);
          }
        } else {
          isRefreshing = false;
          window.location.href = '/login';
          return Promise.reject(error);
        }
      }

      // If already refreshing, queue this request
      return new Promise((resolve) => {
        addRefreshSubscriber((token: string) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          resolve(api(originalRequest));
        });
      });
    }

    // Handle 402 Insufficient Credits
    if (error.response?.status === 402) {
      error.message = 'Out of sparks! Please add more to continue.';
      return Promise.reject(error);
    }

    if (error.response?.data?.detail) {
      error.message = error.response.data.detail;
    }
    return Promise.reject(error);
  }
);

// Helper to append auth token to static file URLs (img src, etc.)
export function authUrl(url: string): string {
  const token = localStorage.getItem('access_token');
  if (!token) return url;
  const base = process.env.NEXT_PUBLIC_API_URL || '';
  const fullUrl = url.startsWith('/') ? `${base}${url}` : url;
  const sep = fullUrl.includes('?') ? '&' : '?';
  return `${fullUrl}${sep}token=${token}`;
}

// Images API
export const imagesApi = {
  list: async (params?: {
    status?: string;
    min_status?: string;
    max_status?: string;
    source?: string;
    in_folder?: boolean;
    skip?: number;
    limit?: number;
  }): Promise<ImageListResponse> => {
    const { data } = await api.get('/images', { params });
    return data;
  },

  batchDelete: async (imageIds: number[]): Promise<{ deleted: number }> => {
    const { data } = await api.post('/images/batch-delete', { image_ids: imageIds });
    return data;
  },

  get: async (id: number): Promise<Image> => {
    const { data } = await api.get(`/images/${id}`);
    return data;
  },

  upload: async (files: File[], folderId?: number): Promise<BatchUploadResponse> => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));

    const params = folderId ? { folder_id: folderId } : undefined;
    const { data } = await api.post('/images/upload/batch', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params,
    });
    return data;
  },

  uploadChunked: async (
    files: File[],
    folderId?: number,
    onProgress?: (uploaded: number, total: number) => void,
    newFolderName?: string,
  ): Promise<BatchUploadResponse> => {
    const CHUNK_SIZE = 15;
    const PARALLEL_CHUNKS = 3;
    const allUploaded: BatchUploadResponse['uploaded'] = [];
    const allFailed: BatchUploadResponse['failed'] = [];
    let jobId: number | null = null;
    let chunkError: string | null = null;
    let sentCount = 0;

    // Build all chunks upfront
    const chunks: File[][] = [];
    for (let i = 0; i < files.length; i += CHUNK_SIZE) {
      chunks.push(files.slice(i, i + CHUNK_SIZE));
    }

    // Send first chunk sequentially to get the job_id
    // Include folder info so the backend can defer folder assignment to job completion
    if (chunks.length > 0) {
      const firstChunk = chunks[0];
      const formData = new FormData();
      firstChunk.forEach((file) => formData.append('files', file));

      const firstChunkParams: Record<string, string | number> = { total_items: files.length };
      if (folderId) firstChunkParams.folder_id = folderId;
      if (newFolderName) firstChunkParams.new_folder_name = newFolderName;

      try {
        const { data } = await api.post<BatchUploadResponse>('/images/upload/batch', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
          params: firstChunkParams,
          timeout: 5 * 60 * 1000, // 5 min per chunk
        });

        jobId = data.job_id;
        allUploaded.push(...data.uploaded);
        allFailed.push(...data.failed);
        sentCount += firstChunk.length;
        onProgress?.(sentCount, files.length);
      } catch (err) {
        chunkError = `Chunk 1-${firstChunk.length} failed: ${err instanceof Error ? err.message : String(err)}`;
        console.error(chunkError);
        for (const file of files) {
          allFailed.push({ filename: file.name, error: 'Upload aborted — first chunk failed' });
        }
        onProgress?.(files.length, files.length);
      }
    }

    // Send remaining chunks in parallel batches
    if (!chunkError && chunks.length > 1 && jobId !== null) {
      const remainingChunks = chunks.slice(1);

      for (let b = 0; b < remainingChunks.length; b += PARALLEL_CHUNKS) {
        const batch = remainingChunks.slice(b, b + PARALLEL_CHUNKS);

        const promises = batch.map((chunk) => {
          const formData = new FormData();
          chunk.forEach((file) => formData.append('files', file));

          return api.post<BatchUploadResponse>('/images/upload/batch', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
            params: { job_id: jobId },
            timeout: 5 * 60 * 1000, // 5 min per chunk
          });
        });

        const results = await Promise.allSettled(promises);

        let batchFailed = false;
        for (let r = 0; r < results.length; r++) {
          const result = results[r];
          const chunk = batch[r];

          if (result.status === 'fulfilled') {
            allUploaded.push(...result.value.data.uploaded);
            allFailed.push(...result.value.data.failed);
            sentCount += chunk.length;
          } else {
            batchFailed = true;
            const errMsg = result.reason instanceof Error ? result.reason.message : String(result.reason);
            chunkError = `Chunk failed: ${errMsg}`;
            console.error(chunkError);
            for (const file of chunk) {
              allFailed.push({ filename: file.name, error: 'Upload chunk failed' });
            }
            sentCount += chunk.length;
          }
        }

        onProgress?.(sentCount, files.length);

        if (batchFailed) {
          // Mark all remaining unsent files as failed
          const nextStart = b + PARALLEL_CHUNKS;
          for (let r = nextStart; r < remainingChunks.length; r++) {
            for (const file of remainingChunks[r]) {
              allFailed.push({ filename: file.name, error: 'Upload aborted — previous chunk failed' });
            }
          }
          onProgress?.(files.length, files.length);
          break;
        }
      }
    }

    // Folder assignment is handled by the backend when the ingest job completes

    // If a chunk failed, throw so the caller's error handler fires — but include partial results
    if (chunkError) {
      const err = new Error(chunkError) as Error & { partialResult: BatchUploadResponse };
      err.partialResult = { uploaded: allUploaded, failed: allFailed, job_id: jobId, folder_error: null };
      throw err;
    }

    return { uploaded: allUploaded, failed: allFailed, job_id: jobId, folder_error: null };
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/images/${id}`);
  },

  getSimilar: async (id: number, limit = 10): Promise<Image[]> => {
    const { data } = await api.get(`/images/${id}/similar`, { params: { limit } });
    return data;
  },

  reprocess: async (
    id: number,
    options?: { tag_prompt?: string; description_prompt?: string; provider?: string; model?: string; temperature?: number; max_tokens_tag?: number; max_tokens_describe?: number }
  ): Promise<StepResponse> => {
    const { data } = await api.post(`/images/${id}/reprocess`, options || {});
    return data;
  },

  tagImage: async (
    id: number,
    options?: { tag_prompt?: string; provider?: string; model?: string; temperature?: number; max_tokens?: number }
  ): Promise<StepResponse> => {
    const { data } = await api.post(`/images/${id}/tag`, options || {});
    return data;
  },

  describeImage: async (
    id: number,
    options?: { description_prompt?: string; provider?: string; model?: string; temperature?: number; max_tokens?: number }
  ): Promise<StepResponse> => {
    const { data } = await api.post(`/images/${id}/describe`, options || {});
    return data;
  },

  embedImage: async (id: number): Promise<StepResponse> => {
    const { data } = await api.post(`/images/${id}/embed`);
    return data;
  },

  getStats: async (): Promise<PipelineStats> => {
    const { data } = await api.get('/images/stats');
    return data;
  },

  getThumbnailUrl: (filename: string): string => {
    return authUrl(`/api/images/thumbnails/${filename}`);
  },

  getImageUrl: (filename: string): string => {
    return authUrl(`/api/images/files/${filename}`);
  },

  getFolders: async (imageId: number): Promise<FolderBrief[]> => {
    const { data } = await api.get(`/images/${imageId}/folders`);
    return data;
  },

  getProcessingCosts: async (imageId: number): Promise<ProcessingCostResponse> => {
    const { data } = await api.get(`/images/${imageId}/processing-costs`);
    return data;
  },
};

// Folders API
export const foldersApi = {
  list: async (params?: { skip?: number; limit?: number }): Promise<FolderListResponse> => {
    const { data } = await api.get('/folders', { params });
    return data;
  },

  get: async (id: number): Promise<Folder> => {
    const { data } = await api.get(`/folders/${id}`);
    return data;
  },

  create: async (folder: { name: string; description?: string }): Promise<Folder> => {
    const { data } = await api.post('/folders', folder);
    return data;
  },

  update: async (id: number, folder: { name?: string; description?: string }): Promise<Folder> => {
    const { data } = await api.patch(`/folders/${id}`, folder);
    return data;
  },

  delete: async (id: number, deleteImages?: boolean): Promise<{ status: string; job_id?: number; total?: number; message?: string }> => {
    const { data } = await api.delete(`/folders/${id}`, {
      params: deleteImages ? { delete_images: true } : undefined,
    });
    return data;
  },

  addImages: async (id: number, imageIds: number[]): Promise<{ added: number }> => {
    const { data } = await api.post(`/folders/${id}/images`, { image_ids: imageIds });
    return data;
  },

  removeImages: async (id: number, imageIds: number[]): Promise<{ removed: number }> => {
    const { data } = await api.delete(`/folders/${id}/images`, {
      data: { image_ids: imageIds },
    });
    return data;
  },

  listImages: async (
    id: number,
    params?: { status?: string; min_status?: string; max_status?: string; skip?: number; limit?: number }
  ): Promise<ImageListResponse> => {
    const { data } = await api.get(`/folders/${id}/images`, { params });
    return data;
  },

  reprocess: async (id: number): Promise<{ job_id: number; total: number }> => {
    const { data } = await api.post(`/folders/${id}/reprocess`);
    return data;
  },

  describe: async (
    id: number,
    params: {
      provider?: string;
      model?: string;
      tag_prompt?: string;
      description_prompt?: string;
      temperature?: number;
      max_tokens_tag?: number;
      max_tokens_describe?: number;
    }
  ): Promise<{ status: string; job_id: number; total: number; message: string }> => {
    const { data } = await api.post(`/folders/${id}/describe`, params);
    return data;
  },

  autoPromptQuestions: async (
    id: number
  ): Promise<{ questions: string[]; sample_analysis: string }> => {
    const { data } = await api.post(`/folders/${id}/auto-prompt/questions`);
    return data;
  },

  autoPromptGenerate: async (
    id: number,
    params: { answers: string[]; sample_analysis: string }
  ): Promise<{ tag_prompt: string; description_prompt: string; explanation: string }> => {
    const { data } = await api.post(`/folders/${id}/auto-prompt/generate`, params);
    return data;
  },
};

// Clusters API
export const clustersApi = {
  list: async (params?: {
    include_archived?: boolean;
    skip?: number;
    limit?: number;
  }): Promise<ClusterListResponse> => {
    const { data } = await api.get('/clusters', { params });
    return data;
  },

  get: async (id: number): Promise<ClusterDetail> => {
    const { data } = await api.get(`/clusters/${id}`);
    return data;
  },

  getImages: async (
    id: number,
    params?: { include_outliers?: boolean; skip?: number; limit?: number }
  ): Promise<Image[]> => {
    const { data } = await api.get(`/clusters/${id}/images`, { params });
    return data;
  },

  rename: async (id: number, displayName: string): Promise<Cluster> => {
    const { data } = await api.patch(`/clusters/${id}/rename`, {
      display_name: displayName,
    });
    return data;
  },

  togglePin: async (id: number): Promise<Cluster> => {
    const { data } = await api.post(`/clusters/${id}/pin`);
    return data;
  },

  archive: async (id: number): Promise<Cluster> => {
    const { data } = await api.post(`/clusters/${id}/archive`);
    return data;
  },

  merge: async (clusterIds: number[], newName?: string): Promise<Cluster> => {
    const { data } = await api.post('/clusters/merge', {
      cluster_ids: clusterIds,
      new_name: newName,
    });
    return data;
  },

  excludeImage: async (clusterId: number, imageId: number): Promise<void> => {
    await api.delete(`/clusters/${clusterId}/images/${imageId}`);
  },

  summarize: async (id: number): Promise<void> => {
    await api.post(`/clusters/${id}/summarize`);
  },

  recluster: async (method?: string): Promise<{ job_id: number }> => {
    const { data } = await api.post('/clusters/recluster', { method });
    return data;
  },

  summarizeAll: async (): Promise<{ job_id: number }> => {
    const { data } = await api.post('/clusters/summarize-all');
    return data;
  },

  exportCluster: (id: number, format: 'json' | 'zip' = 'json'): string => {
    return `/api/clusters/${id}/export?format=${format}`;
  },
};

// Search API
export const searchApi = {
  semantic: async (query: string, limit = 20): Promise<SearchResponse> => {
    const { data } = await api.post('/search', { query, limit });
    return data;
  },

  filter: async (tags: string[]): Promise<Image[]> => {
    const params = new URLSearchParams();
    tags.forEach((t) => params.append('tags', t));
    const { data } = await api.get('/search/filter', { params });
    return data;
  },

  getTagOptions: async (): Promise<string[]> => {
    const { data } = await api.get('/search/tags');
    return data;
  },
};

// Jobs API
export const jobsApi = {
  list: async (params?: {
    job_type?: string;
    status?: string;
    image_id?: number;
    skip?: number;
    limit?: number;
  }): Promise<JobListResponse> => {
    const { data } = await api.get('/jobs', { params });
    return data;
  },

  listByImage: async (imageId: number): Promise<JobListResponse> => {
    const { data } = await api.get('/jobs', { params: { image_id: imageId, limit: 10 } });
    return data;
  },

  get: async (id: number): Promise<Job> => {
    const { data } = await api.get(`/jobs/${id}`);
    return data;
  },

  cancel: async (id: number): Promise<void> => {
    await api.post(`/jobs/${id}/cancel`);
  },

  triggerFullPipeline: async (): Promise<{ job_id: number }> => {
    const { data } = await api.post('/jobs/pipeline/full');
    return data;
  },

  triggerBatchTag: async (): Promise<{ job_id?: number; total: number }> => {
    const { data } = await api.post('/jobs/pipeline/tag');
    return data;
  },

  triggerBatchDescribe: async (): Promise<{ job_id?: number; total: number }> => {
    const { data } = await api.post('/jobs/pipeline/describe');
    return data;
  },

  triggerBatchEmbed: async (): Promise<{ job_id?: number; total: number }> => {
    const { data } = await api.post('/jobs/pipeline/embed');
    return data;
  },

  reprocessAll: async (): Promise<{ job_id: number; total: number }> => {
    const { data } = await api.post('/jobs/pipeline/reprocess-all');
    return data;
  },

  reprocessFailed: async (): Promise<{ job_id: number; total: number }> => {
    const { data } = await api.post('/jobs/pipeline/reprocess-failed');
    return data;
  },

  reprocessSelected: async (imageIds: number[]): Promise<{ job_id: number; total: number }> => {
    const { data } = await api.post('/jobs/pipeline/reprocess-selected', { image_ids: imageIds });
    return data;
  },

  getJobImages: async (jobId: number): Promise<BatchJobImage[]> => {
    const { data } = await api.get(`/jobs/${jobId}/images`);
    return data;
  },

  retry: async (jobId: number): Promise<{ status: string; job_id: number }> => {
    const { data } = await api.post(`/jobs/${jobId}/retry`);
    return data;
  },
};

// Settings API
export const settingsApi = {
  getPrompts: async (): Promise<{
    description_prompt: string;
    tag_prompt: string;
    description_prompt_custom: boolean;
    tag_prompt_custom: boolean;
  }> => {
    const { data } = await api.get('/settings/prompts');
    return data;
  },

  updatePrompts: async (settings: {
    description_prompt?: string | null;
    tag_prompt?: string | null;
  }): Promise<{
    description_prompt: string;
    tag_prompt: string;
    description_prompt_custom: boolean;
    tag_prompt_custom: boolean;
  }> => {
    const { data } = await api.put('/settings/prompts', settings);
    return data;
  },

  resetPrompts: async (promptType: 'description' | 'tag' | 'all' = 'all'): Promise<{
    description_prompt: string;
    tag_prompt: string;
    description_prompt_custom: boolean;
    tag_prompt_custom: boolean;
  }> => {
    const { data } = await api.post('/settings/prompts/reset', null, {
      params: { prompt_type: promptType },
    });
    return data;
  },

  suggestPrompt: async (params: {
    current_prompt: string;
    change_request: string;
    prompt_type: 'description' | 'tag';
  }): Promise<{ suggested_prompt: string }> => {
    const { data } = await api.post('/settings/prompts/suggest', params);
    return data;
  },

  // Preset CRUD
  listPresets: async (): Promise<PromptPreset[]> => {
    const { data } = await api.get('/settings/presets');
    return data;
  },

  getPreset: async (id: number): Promise<PromptPreset> => {
    const { data } = await api.get(`/settings/presets/${id}`);
    return data;
  },

  createPreset: async (preset: {
    name: string;
    tag_prompt: string;
    description_prompt: string;
  }): Promise<PromptPreset> => {
    const { data } = await api.post('/settings/presets', preset);
    return data;
  },

  updatePreset: async (
    id: number,
    preset: { name?: string; tag_prompt?: string; description_prompt?: string }
  ): Promise<PromptPreset> => {
    const { data } = await api.put(`/settings/presets/${id}`, preset);
    return data;
  },

  deletePreset: async (id: number): Promise<void> => {
    await api.delete(`/settings/presets/${id}`);
  },

  activatePreset: async (id: number): Promise<PromptPreset> => {
    const { data } = await api.post(`/settings/presets/${id}/activate`);
    return data;
  },

  getClusteringConfig: async (): Promise<ClusteringConfig> => {
    const { data } = await api.get('/settings/clustering');
    return data;
  },

  updateClusteringConfig: async (
    config: Partial<ClusteringConfig>
  ): Promise<ClusteringConfig> => {
    const { data } = await api.put('/settings/clustering', config);
    return data;
  },

  resetClusteringConfig: async (): Promise<ClusteringConfig> => {
    const { data } = await api.post('/settings/clustering/reset');
    return data;
  },

  getBaseModel: async (): Promise<{ base_model: string }> => {
    const { data } = await api.get('/settings/base-model');
    return data;
  },

  updateBaseModel: async (base_model: string): Promise<{ base_model: string }> => {
    const { data } = await api.put('/settings/base-model', { base_model });
    return data;
  },

  getEditModel: async (): Promise<{ edit_model: string }> => {
    const { data } = await api.get('/settings/edit-model');
    return data;
  },

  updateEditModel: async (edit_model: string): Promise<{ edit_model: string }> => {
    const { data } = await api.put('/settings/edit-model', { edit_model });
    return data;
  },

  getGenerationConfig: async (baseModel?: string): Promise<GenerationConfig> => {
    const { data } = await api.get('/settings/generation', {
      params: baseModel ? { base_model: baseModel } : undefined,
    });
    return data;
  },

  updateGenerationConfig: async (config: Partial<GenerationConfig>, baseModel?: string): Promise<GenerationConfig> => {
    const { data } = await api.put('/settings/generation', config, {
      params: baseModel ? { base_model: baseModel } : undefined,
    });
    return data;
  },

  resetGenerationConfig: async (baseModel?: string): Promise<GenerationConfig> => {
    const { data } = await api.post('/settings/generation/reset', null, {
      params: baseModel ? { base_model: baseModel } : undefined,
    });
    return data;
  },

  getTrainingConfig: async (baseModel?: string): Promise<TrainingConfig> => {
    const { data } = await api.get('/settings/training', {
      params: baseModel ? { base_model: baseModel } : undefined,
    });
    return data;
  },

  updateTrainingConfig: async (config: Partial<TrainingConfig>, baseModel?: string): Promise<TrainingConfig> => {
    const { data } = await api.put('/settings/training', config, {
      params: baseModel ? { base_model: baseModel } : undefined,
    });
    return data;
  },

  resetTrainingConfig: async (baseModel?: string): Promise<TrainingConfig> => {
    const { data } = await api.post('/settings/training/reset', null, {
      params: baseModel ? { base_model: baseModel } : undefined,
    });
    return data;
  },

  // Edit config
  getEditConfig: async (editModel?: string): Promise<EditConfig> => {
    const { data } = await api.get('/settings/edit', {
      params: editModel ? { edit_model: editModel } : undefined,
    });
    return data;
  },

  updateEditConfig: async (config: Partial<EditConfig>, editModel?: string): Promise<EditConfig> => {
    const { data } = await api.put('/settings/edit', config, {
      params: editModel ? { edit_model: editModel } : undefined,
    });
    return data;
  },

  resetEditConfig: async (editModel?: string): Promise<EditConfig> => {
    const { data } = await api.post('/settings/edit/reset', null, {
      params: editModel ? { edit_model: editModel } : undefined,
    });
    return data;
  },

  // Platform API keys (admin)
  getApiKeys: async (): Promise<APIKeyInfo[]> => {
    const { data } = await api.get('/settings/api-keys');
    return data;
  },

  saveApiKey: async (provider: string, key: string): Promise<APIKeyInfo> => {
    const { data } = await api.put(`/settings/api-keys/${provider}`, { key });
    return data;
  },

  validateApiKey: async (provider: string): Promise<APIKeyInfo> => {
    const { data } = await api.post(`/settings/api-keys/${provider}/validate`);
    return data;
  },

  deleteApiKey: async (provider: string): Promise<void> => {
    await api.delete(`/settings/api-keys/${provider}`);
  },

  // Provider config
  getProviderConfig: async (): Promise<ProviderConfig> => {
    const { data } = await api.get('/settings/providers');
    return data;
  },

  updateProviderConfig: async (config: Partial<ProviderConfig>): Promise<ProviderConfig> => {
    const { data } = await api.put('/settings/providers', config);
    return data;
  },

  resetProviderConfig: async (): Promise<ProviderConfig> => {
    const { data } = await api.post('/settings/providers/reset');
    return data;
  },

  // Model discovery
  getProviderModels: async (provider: string): Promise<ProviderModel[]> => {
    const { data } = await api.get(`/settings/models/${provider}`);
    return data;
  },

  // Sentry DSN (public, no auth)
  getSentryDsn: async (): Promise<{ dsn: string | null }> => {
    const { data } = await api.get('/settings/sentry-dsn');
    return data;
  },
};

// Generation API
export const generationApi = {
  // LoRA
  trainLora: async (params: {
    name: string;
    trigger_word?: string;
    folder_id?: number;
    cluster_id?: number;
    description?: string;
    steps?: number;
    is_style?: boolean;
    base_model?: string;
    use_captions?: boolean;
    caption_include_tags?: boolean;
    caption_include_description?: boolean;
    learning_rate?: number;
    example_prompts?: string[];
  }): Promise<{ status: string; lora_model_id: number; job_id: number }> => {
    const { data } = await api.post('/generation/lora/train', params);
    return data;
  },

  uploadLora: async (params: {
    name: string;
    trigger_word?: string;
    base_model?: string;
    description?: string;
    example_prompts?: string[];
    file: File;
  }): Promise<LoraModel> => {
    const formData = new FormData();
    formData.append('name', params.name);
    if (params.trigger_word) formData.append('trigger_word', params.trigger_word);
    formData.append('base_model', params.base_model || 'flux-dev');
    if (params.description) formData.append('description', params.description);
    if (params.example_prompts?.length) formData.append('example_prompts', JSON.stringify(params.example_prompts));
    formData.append('file', params.file);
    const { data } = await api.post('/generation/lora/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 5 * 60 * 1000,
    });
    return data;
  },

  listLora: async (params?: {
    status?: string;
    base_model?: string;
    skip?: number;
    limit?: number;
  }): Promise<LoraListResponse> => {
    const { data } = await api.get('/generation/lora', { params });
    return data;
  },

  getLora: async (id: number): Promise<LoraModel> => {
    const { data } = await api.get(`/generation/lora/${id}`);
    return data;
  },

  deleteLora: async (id: number): Promise<void> => {
    await api.delete(`/generation/lora/${id}`);
  },

  recoverLoraTraining: async (loraId: number): Promise<{ status: string; lora_url?: string; request_id?: string; error?: string; fal_status?: string }> => {
    const { data } = await api.post(`/generation/lora/${loraId}/recover`);
    return data;
  },

  retryLoraTraining: async (loraId: number): Promise<{ status: string; lora_model_id: number; job_id: number }> => {
    const { data } = await api.post(`/generation/lora/${loraId}/retry`);
    return data;
  },

  downloadLoraWeights: async (loraId: number): Promise<{ status: string }> => {
    const { data } = await api.post(`/generation/lora/${loraId}/download-weights`);
    return data;
  },

  downloadAllLoraWeights: async (): Promise<{ status: string; count: number }> => {
    const { data } = await api.post('/generation/lora/download-all-weights');
    return data;
  },

  // Prompt expansion
  expandPrompt: async (prompt: string): Promise<{ expanded_prompt: string }> => {
    const { data } = await api.post('/generation/expand-prompt', { prompt });
    return data;
  },

  // Generation
  generate: async (params: {
    prompt: string;
    negative_prompt?: string;
    lora_model_id?: number;
    lora_scale?: number;
    loras?: Array<{ lora_model_id: number; lora_scale: number }>;
    base_model?: string;
    width?: number;
    height?: number;
    num_inference_steps?: number;
    guidance_scale?: number;
    seed?: number;
    num_images?: number;
    resolution?: string;
    aspect_ratio?: string;
    safety_tolerance?: string;
    enable_web_search?: boolean;
  }): Promise<{ status: string; job_id: number; generated_image_ids: number[] }> => {
    const { data } = await api.post('/generation/generate', params);
    return data;
  },

  listImages: async (params?: {
    lora_model_id?: number;
    status?: string;
    skip?: number;
    limit?: number;
  }): Promise<GeneratedImageListResponse> => {
    const { data } = await api.get('/generation/images', { params });
    return data;
  },

  getImage: async (id: number): Promise<GeneratedImage> => {
    const { data } = await api.get(`/generation/images/${id}`);
    return data;
  },

  deleteImage: async (id: number): Promise<void> => {
    await api.delete(`/generation/images/${id}`);
  },

  getImageUrl: (id: number): string => {
    return authUrl(`/api/generation/images/${id}/file`);
  },

  getThumbnailUrl: (filename: string): string => {
    return authUrl(`/api/generation/thumbnails/${filename}`);
  },

  // Evaluations
  startEvaluation: async (
    loraId: number,
    params: {
      sample_count?: number;
      creative_count?: number;
      metrics_enabled?: string[];
      generation_params?: Record<string, unknown>;
      vision_eval_provider?: string;
    }
  ): Promise<{ status: string; evaluation_id: number; job_id: number }> => {
    const { data } = await api.post(`/generation/lora/${loraId}/evaluate`, params);
    return data;
  },

  listEvaluations: async (
    loraId: number,
    params?: { skip?: number; limit?: number }
  ): Promise<EvaluationListResponse> => {
    const { data } = await api.get(`/generation/lora/${loraId}/evaluations`, { params });
    return data;
  },

  getEvaluation: async (evalId: number): Promise<LoraEvaluation> => {
    const { data } = await api.get(`/generation/evaluations/${evalId}`);
    return data;
  },

  deleteEvaluation: async (evalId: number): Promise<void> => {
    await api.delete(`/generation/evaluations/${evalId}`);
  },

  getLoraWeightsUrl: (loraId: number): string => {
    return authUrl(`/api/generation/lora/${loraId}/weights`);
  },

  getEvalGeneratedImageUrl: (evalId: number, pairId: number): string => {
    return authUrl(`/api/generation/evaluations/${evalId}/pairs/${pairId}/generated-file`);
  },
};

// Edit API
export const editApi = {
  edit: async (params: {
    prompt?: string;
    negative_prompt?: string;
    source_image_ids?: number[];
    source_generated_ids?: number[];
    source_upload_keys?: string[];
    edit_model?: string;
    image_size?: string | { width: number; height: number };
    num_images?: number;
    seed?: number;
    output_format?: string;
    enable_prompt_expansion?: boolean;
    enable_safety_checker?: boolean;
    resolution?: string;
    aspect_ratio?: string;
    enable_occlusion_prevention?: boolean;
    safety_tolerance?: string;
    enable_web_search?: boolean;
  }): Promise<{ status: string; job_id: number; generated_image_ids: number[] }> => {
    const { data } = await api.post('/edit', params);
    return data;
  },

  uploadSource: async (file: File): Promise<{ object_key: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/edit/upload-source', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  listImages: async (params?: {
    skip?: number;
    limit?: number;
  }): Promise<GeneratedImageListResponse> => {
    const { data } = await api.get('/edit/images', { params });
    return data;
  },

  getImage: async (id: number): Promise<GeneratedImage> => {
    const { data } = await api.get(`/edit/images/${id}`);
    return data;
  },

  deleteImage: async (id: number): Promise<void> => {
    await api.delete(`/edit/images/${id}`);
  },

  getImageUrl: (id: number): string => {
    return authUrl(`/api/edit/images/${id}/file`);
  },

  getThumbnailUrl: (filename: string): string => {
    return authUrl(`/api/edit/thumbnails/${filename}`);
  },
};

// Vision API
export const visionApi = {
  analyze: async (params: {
    source_image_id?: number;
    source_generated_id?: number;
    source_upload_key?: string;
    provider: string;
    model?: string;
    mode: 'tag' | 'describe' | 'custom';
    custom_prompt?: string;
    tag_prompt?: string;
    description_prompt?: string;
    temperature?: number;
    max_tokens?: number;
  }): Promise<{ id: number; mode: string; tags?: string[]; description?: string; model: string; duration_ms?: number; cost_sparks?: number | null }> => {
    const { data } = await api.post('/vision/analyze', params);
    return data;
  },

  listResults: async (skip = 0, limit = 50): Promise<{
    items: Array<{
      id: number;
      mode: string;
      provider: string;
      model: string;
      prompt_text?: string;
      result_tags?: string[];
      result_text?: string;
      duration_ms?: number;
      cost_sparks?: number | null;
      source_image_id?: number;
      source_generated_id?: number;
      source_object_key?: string;
      created_at: string;
    }>;
    total: number;
    skip: number;
    limit: number;
  }> => {
    const { data } = await api.get('/vision/results', { params: { skip, limit } });
    return data;
  },

  deleteResult: async (id: number): Promise<void> => {
    await api.delete(`/vision/results/${id}`);
  },

  uploadSource: async (file: File): Promise<{ object_key: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/vision/upload-source', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },
};

// Logs API
export const logsApi = {
  list: async (params?: {
    category?: string;
    level?: string;
    image_id?: number;
    job_id?: number;
    search?: string;
    skip?: number;
    limit?: number;
  }): Promise<LogListResponse> => {
    const { data } = await api.get('/logs', { params });
    return data;
  },

  stats: async (): Promise<LogStats> => {
    const { data } = await api.get('/logs/stats');
    return data;
  },

  cleanup: async (days?: number): Promise<{ deleted: number }> => {
    const { data } = await api.delete('/logs/cleanup', { params: { days } });
    return data;
  },
};

// Auth API
export const authApi = {
  login: async (email: string, password: string): Promise<TokenResponse> => {
    const { data } = await api.post('/auth/login', { email, password });
    return data;
  },

  register: async (email: string, password: string, displayName?: string): Promise<TokenResponse> => {
    const { data } = await api.post('/auth/register', { email, password, display_name: displayName || null });
    return data;
  },

  refresh: async (refreshToken: string): Promise<TokenResponse> => {
    const { data } = await api.post('/auth/refresh', { refresh_token: refreshToken });
    return data;
  },

  me: async (): Promise<AuthUser> => {
    const { data } = await api.get('/auth/me');
    return data;
  },
};

// Billing API
export const billingApi = {
  getBalance: async (): Promise<UserBalance> => {
    const { data } = await api.get('/billing/balance');
    return data;
  },

  getTransactions: async (skip = 0, limit = 50): Promise<TransactionListResponse> => {
    const { data } = await api.get('/billing/transactions', { params: { skip, limit } });
    return data;
  },

  getGenerationCosts: async (): Promise<GenerationCosts> => {
    const { data } = await api.get('/billing/generation-costs');
    return data;
  },

  getVisionCosts: async (): Promise<VisionCosts> => {
    const { data } = await api.get('/billing/vision-costs');
    return data;
  },

  getVisionCostsEstimate: async (params: {
    width?: number;
    height?: number;
    folder_id?: number;
  }): Promise<VisionCosts> => {
    const { data } = await api.post('/billing/vision-costs', params);
    return data;
  },

  getEditCosts: async (): Promise<EditCosts> => {
    const { data } = await api.get('/billing/edit-costs');
    return data;
  },

  getTrainingCosts: async (): Promise<TrainingCosts> => {
    const { data } = await api.get('/billing/training-costs');
    return data;
  },

  getUsage: async (startDate?: string, endDate?: string): Promise<UsageSummary> => {
    const { data } = await api.get('/billing/usage', {
      params: { start_date: startDate, end_date: endDate },
    });
    return data;
  },

  // Admin endpoints
  adminGetUsers: async (): Promise<AdminUserBalance[]> => {
    const { data } = await api.get('/billing/admin/users');
    return data;
  },

  adminGetUserUsage: async (userId: number, startDate?: string, endDate?: string): Promise<UsageSummary> => {
    const { data } = await api.get(`/billing/admin/users/${userId}/usage`, {
      params: { start_date: startDate, end_date: endDate },
    });
    return data;
  },

  adminAddCredits: async (userId: number, amount: number, description: string): Promise<UserBalance> => {
    const { data } = await api.post(`/billing/admin/users/${userId}/credits`, { amount, description });
    return data;
  },

  adminGetSummary: async (startDate?: string, endDate?: string): Promise<PlatformUsageSummary> => {
    const { data } = await api.get('/billing/admin/summary', {
      params: { start_date: startDate, end_date: endDate },
    });
    return data;
  },

  adminGetCatalog: async (): Promise<CostCatalogEntry[]> => {
    const { data } = await api.get('/billing/admin/catalog');
    return data;
  },

  adminCreateCatalogEntry: async (entry: Omit<CostCatalogEntry, 'id' | 'is_active' | 'created_at' | 'updated_at'>): Promise<CostCatalogEntry> => {
    const { data } = await api.post('/billing/admin/catalog', entry);
    return data;
  },

  adminUpdateCatalogEntry: async (id: number, entry: Omit<CostCatalogEntry, 'id' | 'is_active' | 'created_at' | 'updated_at'>): Promise<CostCatalogEntry> => {
    const { data } = await api.put(`/billing/admin/catalog/${id}`, entry);
    return data;
  },

  adminDeleteCatalogEntry: async (id: number): Promise<void> => {
    await api.delete(`/billing/admin/catalog/${id}`);
  },

  adminBulkUpdateModel: async (data: ModelBulkUpdateRequest): Promise<CostCatalogEntry[]> => {
    const { data: result } = await api.put('/billing/admin/catalog/model-bulk', data);
    return result;
  },

  adminGetLogs: async (params?: {
    skip?: number;
    limit?: number;
    user_search?: string;
    provider?: string;
    operation?: string;
    start_date?: string;
    end_date?: string;
  }): Promise<BillingLogListResponse> => {
    const { data } = await api.get('/billing/admin/logs', { params });
    return data;
  },

  adminSearchOperations: async (params?: {
    skip?: number;
    limit?: number;
    trace_id?: string;
    job_id?: number;
    user_id?: number;
    image_id?: number;
    operation?: string;
    status?: string;
    start_date?: string;
    end_date?: string;
  }): Promise<DecisionListResponse> => {
    const { data } = await api.get('/billing/admin/operations', { params });
    return data;
  },

  adminGetTrace: async (traceId: string): Promise<TraceResponse> => {
    const { data } = await api.get(`/billing/admin/trace/${traceId}`);
    return data;
  },

  adminGetReconciliation: async (params?: {
    start_date?: string;
    end_date?: string;
    operation?: string;
    provider?: string;
    threshold_pct?: number;
  }): Promise<ReconciliationResponse> => {
    const { data } = await api.get('/billing/admin/reconciliation', { params });
    return data;
  },

  adminGetAnomalies: async (params?: {
    skip?: number;
    limit?: number;
    anomaly_type?: string;
    resolved?: boolean;
    provider?: string;
    operation?: string;
    start_date?: string;
    end_date?: string;
  }): Promise<AnomalyListResponse> => {
    const { data } = await api.get('/billing/admin/anomalies', { params });
    return data;
  },

  adminGetAnomalySummary: async (): Promise<AnomalySummaryResponse> => {
    const { data } = await api.get('/billing/admin/anomalies/summary');
    return data;
  },

  adminResolveAnomaly: async (id: number): Promise<void> => {
    await api.patch(`/billing/admin/anomalies/${id}/resolve`);
  },

  adminCreateCatalogFromAnomaly: async (id: number): Promise<CostCatalogEntry> => {
    const { data } = await api.post(`/billing/admin/anomalies/${id}/create-catalog-entry`);
    return data;
  },

  adminGetMetrics: async (hours: number = 24): Promise<MetricsResponse> => {
    const { data } = await api.get('/billing/admin/metrics', { params: { hours } });
    return data;
  },

  getEvaluationCosts: async (params: {
    base_model?: string;
    sample_count?: number;
    creative_count?: number;
    vision_eval_provider?: string;
  }): Promise<EvaluationCostsResponse> => {
    const { data } = await api.get('/billing/evaluation-costs', { params });
    return data;
  },

  getSummarizeCosts: async (clusterCount: number = 1): Promise<SummarizeCostsResponse> => {
    const { data } = await api.get('/billing/summarize-costs', { params: { cluster_count: clusterCount } });
    return data;
  },
};

export default api;
