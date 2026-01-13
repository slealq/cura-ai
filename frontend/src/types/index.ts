export interface ImageMetadata {
  tags: Record<string, string[]>;
  dominant_colors: Array<{ hex: string; weight: number }>;
  caption_short: string | null;
  description_long: string | null;
  tagging_model: string | null;
  caption_model: string | null;
  embedding_model: string | null;
}

export interface Image {
  id: number;
  source: string;
  original_filename: string | null;
  object_key: string;
  width: number | null;
  height: number | null;
  file_size: number | null;
  mime_type: string | null;
  status: string;
  thumbnail_uri_small: string | null;
  thumbnail_uri_medium: string | null;
  thumbnail_uri_large: string | null;
  created_at: string;
  ingested_at: string | null;
  metadata: ImageMetadata | null;
}

export interface ImageListResponse {
  items: Image[];
  total: number;
  skip: number;
  limit: number;
}

export interface Cluster {
  id: number;
  method: string;
  run_id: string;
  size: number;
  summary_title: string | null;
  summary_description: string | null;
  common_tags: Record<string, string[]>;
  representative_image_ids: number[];
  display_name: string | null;
  is_pinned: boolean;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface ClusterListResponse {
  items: Cluster[];
  total: number;
  skip: number;
  limit: number;
}

export interface ClusterDetail extends Cluster {
  images: Image[];
}

export interface Job {
  id: number;
  celery_task_id: string | null;
  job_type: string;
  status: string;
  progress: number;
  total_items: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  result: Record<string, unknown> | null;
}

export interface JobListResponse {
  items: Job[];
  total: number;
  skip: number;
  limit: number;
}

export interface PipelineStats {
  total_images: number;
  pending: number;
  ingested: number;
  tagged: number;
  described: number;
  embedded: number;
  clustered: number;
  failed: number;
  total_clusters: number;
}

export interface TagFilterOptions {
  style: string[];
  subject: string[];
  medium: string[];
  mood: string[];
  color_palette: string[];
  lighting: string[];
  materials: string[];
  composition: string[];
  typography: string[];
  era_reference: string[];
}

export interface SearchResponse {
  images: Image[];
  query: string;
  total: number;
}

export interface UploadResponse {
  image_id: number;
  filename: string;
  status: string;
  message: string;
}

export interface BatchUploadResponse {
  uploaded: UploadResponse[];
  failed: Array<{ filename: string; error: string }>;
  job_id: number | null;
}
