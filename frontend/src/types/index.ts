export interface ImageMetadata {
  tags: string[];
  dominant_colors: Array<{ hex: string; weight: number }>;
  description_long: string | null;
  tagging_model: string | null;
  caption_model: string | null;
  embedding_model: string | null;
  tag_prompt_text: string | null;
  description_prompt_text: string | null;
  tagged_at: string | null;
  described_at: string | null;
  embedded_at: string | null;
  tagging_duration_ms: number | null;
  caption_duration_ms: number | null;
  embedding_duration_ms: number | null;
}

export interface ProcessingCostOperation {
  operation: string;
  provider: string;
  model: string;
  sparks: number;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface ProcessingCostResponse {
  operations: ProcessingCostOperation[];
  total_sparks: number;
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
  common_tags: string[];
  representative_image_ids: number[];
  display_name: string | null;
  is_pinned: boolean;
  is_archived: boolean;
  cover_thumbnail_url: string | null;
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
  parameters: Record<string, unknown> | null;
  image_id: number | null;
  image_filename: string | null;
  image_thumbnail: string | null;
  charged_cost: number | null;
  charged_sparks: number | null;
}

export interface StepResponse {
  status: string;
  image_id: number;
  step: string;
  job_id: number;
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

export interface ScoredImage {
  image: Image;
  score: number;
  semantic_score: number;
  text_score: number;
}

export interface SearchResponse {
  results: ScoredImage[];
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
  folder_error: string | null;
}

export interface LogEntry {
  id: number;
  level: 'debug' | 'info' | 'warning' | 'error';
  category: 'api_call' | 'task' | 'pipeline' | 'system';
  image_id: number | null;
  job_id: number | null;
  task_name: string | null;
  message: string;
  provider: string | null;
  model: string | null;
  operation: string | null;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  success: boolean | null;
  extra: Record<string, unknown> | null;
  created_at: string;
}

export interface LogListResponse {
  items: LogEntry[];
  total: number;
  skip: number;
  limit: number;
}

export interface LogStats {
  total_logs: number;
  api_calls: number;
  errors: number;
  total_tokens: number;
  avg_duration_ms: number | null;
}

export interface BatchJobImage {
  id: number;
  original_filename: string | null;
  thumbnail: string | null;
}

export interface PromptPreset {
  id: number;
  name: string;
  tag_prompt: string;
  description_prompt: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface FolderPreviewImage {
  id: number;
  thumbnail_uri_small: string | null;
  thumbnail_uri_medium: string | null;
}

export interface Folder {
  id: number;
  name: string;
  description: string | null;
  image_count: number;
  cover_thumbnail_url: string | null;
  created_at: string;
  updated_at: string;
  preview_images: FolderPreviewImage[];
}

export interface FolderListResponse {
  items: Folder[];
  total: number;
  skip: number;
  limit: number;
}

export interface FolderBrief {
  id: number;
  name: string;
}

export interface ClusteringConfig {
  method: string;
  use_umap: boolean;
  umap_n_components: number;
  umap_n_neighbors: number;
  umap_min_dist: number;
  umap_metric: string;
  hdbscan_min_cluster_size: number;
  hdbscan_min_samples: number;
  hdbscan_cluster_selection_method: string;
  kmeans_max_clusters: number;
}

export interface LoraPreviewImage {
  id: number;
  thumbnail_uri_small: string | null;
}

export interface LatestEvaluationSummary {
  id: number;
  status: string;
  overall_score: number | null;
  avg_embedding_similarity: number | null;
  avg_vision_score: number | null;
  completed_at: string | null;
}

export interface LoraModel {
  id: number;
  name: string;
  trigger_word: string | null;
  description: string | null;
  folder_id: number | null;
  folder_name: string | null;
  cluster_id: number | null;
  cluster_name: string | null;
  base_model: string;
  training_provider: string;
  training_config: Record<string, unknown> | null;
  status: string;
  error_message: string | null;
  lora_url: string | null;
  training_images_count: number;
  job_id: number | null;
  source_preview_images: LoraPreviewImage[];
  latest_evaluation: LatestEvaluationSummary | null;
  weights_object_key: string | null;
  file_size: number | null;
  file_hash: string | null;
  weights_downloaded_at: string | null;
  has_local_weights: boolean;
  example_prompts: string[] | null;
  created_at: string;
  training_started_at: string | null;
  training_completed_at: string | null;
  updated_at: string;
}

export interface LoraListResponse {
  items: LoraModel[];
  total: number;
  skip: number;
  limit: number;
}

export interface LoraUsed {
  lora_model_id: number;
  lora_model_name: string;
  lora_scale: number;
}

export interface GeneratedImage {
  id: number;
  prompt: string;
  negative_prompt: string | null;
  base_model: string;
  generation_provider: string;
  lora_model_id: number | null;
  lora_model_name: string | null;
  lora_scale: number | null;
  loras: LoraUsed[];
  generation_params: Record<string, unknown> | null;
  status: string;
  error_message: string | null;
  object_key: string | null;
  width: number | null;
  height: number | null;
  file_size: number | null;
  mime_type: string | null;
  thumbnail_uri_small: string | null;
  thumbnail_uri_medium: string | null;
  job_id: number | null;
  cost_sparks: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface GeneratedImageListResponse {
  items: GeneratedImage[];
  total: number;
  skip: number;
  limit: number;
}

export interface GenerationConfig {
  width: number;
  height: number;
  num_inference_steps: number;
  guidance_scale: number;
  default_lora_scale: number;
}

export interface TrainingConfig {
  steps?: number;
  is_style?: boolean;
  learning_rate?: number;
}

export interface EditConfig {
  image_size: string | { width: number; height: number };
  num_images: number;
  output_format: string;
  enable_prompt_expansion: boolean;
  enable_safety_checker: boolean;
}

export interface APIKeyInfo {
  provider: string;
  key_suffix: string | null;
  status: string;
  last_validated_at: string | null;
  last_error: string | null;
}

export interface ProviderConfig {
  vision_provider: string;
  embedding_provider: string;
  openai_vision_model: string;
  openai_embedding_model: string;
  anthropic_vision_model: string;
  fal_vision_model: string;
  max_tokens_tagging: number;
  max_tokens_description: number;
  max_tokens_summarization: number;
  language_provider: string;
  openai_language_model: string;
  anthropic_language_model: string;
  fal_language_model: string;
  max_tokens_expansion: number;
  max_tokens_suggestion: number;
  vision_temperature: number;
}

export interface ProviderModel {
  id: string;
  name: string;
  capabilities: string[];
}

export interface EvaluationPair {
  id: number;
  pair_type: string;
  original_image_id: number | null;
  original_thumbnail: string | null;
  original_object_key: string | null;
  prompt_used: string | null;
  generated_object_key: string | null;
  generated_thumbnail_small: string | null;
  generated_thumbnail_medium: string | null;
  generated_width: number | null;
  generated_height: number | null;
  embedding_similarity: number | null;
  vision_score: number | null;
  vision_assessment: string | null;
  clip_image_score: number | null;
  clip_text_score: number | null;
  pair_score: number | null;
  metrics_detail: {
    style_fidelity?: number;
    subject_accuracy?: number;
    detail_preservation?: number;
    realism?: number;
    prompt_adherence?: number;
    detail_quality?: number;
    pair_type?: string;
  } | null;
  status: string;
  error_message: string | null;
}

export interface LoraEvaluation {
  id: number;
  lora_model_id: number;
  lora_model_name: string | null;
  sample_count: number;
  config: Record<string, unknown> | null;
  status: string;
  error_message: string | null;
  overall_score: number | null;
  avg_embedding_similarity: number | null;
  avg_vision_score: number | null;
  assessment_summary: string | null;
  aggregate_results: Record<string, unknown> | null;
  training_config: Record<string, unknown> | null;
  training_images_count: number;
  job_id: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  pairs: EvaluationPair[];
}

export interface EvaluationListItem {
  id: number;
  lora_model_id: number;
  sample_count: number;
  status: string;
  overall_score: number | null;
  avg_embedding_similarity: number | null;
  avg_vision_score: number | null;
  job_id: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface EvaluationListResponse {
  items: EvaluationListItem[];
  total: number;
  skip: number;
  limit: number;
}

export interface AuthUser {
  id: number;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: AuthUser;
}

// --- Billing types ---

export interface UserBalance {
  balance: number;
  reserved: number;
  available: number;
  currency: string;
}

export interface BalanceTransaction {
  id: number;
  amount: number;
  transaction_type: string;
  description: string;
  reference_id: number | null;
  created_by: number | null;
  created_at: string;
}

export interface TransactionListResponse {
  items: BalanceTransaction[];
  total: number;
}

export interface OperationUsageDetail {
  operation: string;
  count: number;
  total_sparks: number;
  avg_sparks: number;
}

export interface UsageSummary {
  total_cost: number;
  by_operation: Record<string, number>;
  by_provider: Record<string, number>;
  record_count: number;
  by_operation_detail: OperationUsageDetail[];
}

export interface AdminUserBalance {
  user_id: number;
  email: string;
  display_name: string | null;
  balance: number;
  total_spent: number;
  last_activity: string | null;
}

export interface CostCatalogEntry {
  id: number;
  provider: string;
  model: string;
  operation: string;
  cost_per_input_token: number | null;
  cost_per_output_token: number | null;
  cost_per_call: number | null;
  platform_markup: number;
  pricing_rules?: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ModelBulkUpdateRequest {
  provider: string;
  model: string;
  cost_per_input_token: number;
  cost_per_output_token: number;
  cost_per_call: number;
  operations: { operation: string; platform_markup: number }[];
}

export interface GenerationCosts {
  costs: Record<string, Record<string, number>>;
  expand_prompt_cost: number;
  variable_pricing_models?: string[];
}

export interface GenerationEstimateResponse {
  estimated_sparks: number;
  base_model: string;
}

export interface VisionCostsEstimationBasis {
  width: number;
  height: number;
  source: 'provided' | 'folder_avg' | 'default';
}

export interface VisionCosts {
  costs: Record<string, Record<string, Record<string, number>>>;
  estimation_basis?: VisionCostsEstimationBasis | null;
}

export interface EditCosts {
  costs: Record<string, number>;
}

export interface TrainingCosts {
  costs: Record<string, number>;
}

export interface PlatformUsageSummary {
  total_raw_cost: number;
  total_charged: number;
  margin: number;
  by_provider: Record<string, number>;
  by_operation: Record<string, number>;
  record_count: number;
}

export interface BillingLogEntry {
  id: number;
  user_id: number;
  user_email: string;
  user_display_name: string | null;
  pipeline_log_id: number | null;
  operation: string;
  provider: string;
  model: string;
  input_tokens: number | null;
  output_tokens: number | null;
  raw_cost: number;
  charged_cost: number;
  detail: {
    cost_per_input_token: number;
    cost_per_output_token: number;
    cost_per_call: number;
    input_cost: number;
    output_cost: number;
    call_cost: number;
    platform_markup: number;
    sparks: number;
  } | null;
  created_at: string;
}

export interface BillingLogListResponse {
  items: BillingLogEntry[];
  total: number;
  skip: number;
  limit: number;
}

// --- Reconciliation / Anomalies / Metrics types ---

export interface ReconciliationRow {
  operation: string;
  provider: string;
  model: string;
  total_decisions: number;
  avg_estimated_sparks: number;
  avg_actual_sparks: number;
  avg_delta: number;
  avg_delta_pct: number;
  min_delta: number;
  max_delta: number;
  total_estimated: number;
  total_actual: number;
}

export interface ReconciliationResponse {
  items: ReconciliationRow[];
  threshold_pct: number;
  threshold_violations: number;
}

export interface AnomalyEntry {
  id: number;
  user_id: number | null;
  anomaly_type: string;
  provider: string | null;
  model: string | null;
  operation: string | null;
  detail: Record<string, unknown> | null;
  resolved: boolean;
  created_at: string;
}

export interface AnomalyListResponse {
  items: AnomalyEntry[];
  total: number;
  skip: number;
  limit: number;
}

export interface AnomalyGroupSummary {
  anomaly_type: string;
  provider: string | null;
  model: string | null;
  operation: string | null;
  count: number;
}

export interface AnomalySummaryResponse {
  groups: AnomalyGroupSummary[];
  total_unresolved: number;
  last_24h_count: number;
}

export interface OperationMetric {
  operation: string;
  count: number;
  avg_sparks: number;
  failure_count: number;
}

export interface ProviderMetric {
  provider: string;
  count: number;
  avg_sparks: number;
  failure_count: number;
}

export interface MetricAlert {
  level: string;
  message: string;
}

export interface MetricsResponse {
  hours: number;
  total_operations: number;
  ops_per_hour: number;
  failure_rate: number;
  cancel_rate: number;
  pending_decisions: number;
  avg_delta_pct: number;
  catalog_miss_count: number;
  anomalies_by_type: Record<string, number>;
  by_operation: OperationMetric[];
  by_provider: ProviderMetric[];
  alerts: MetricAlert[];
}

export interface EvaluationCostsResponse {
  breakdown: {
    generate_per_image: number;
    describe_per_image: number;
    embed_per_image: number;
    vision_eval_per_image: number;
    creative_prompts: number;
    assessment: number;
    per_reference_pair: number;
    per_creative_pair: number;
  };
  totals: {
    reference: number;
    creative: number;
    overhead: number;
    total: number;
  };
  params: {
    base_model: string;
    sample_count: number;
    creative_count: number;
  };
  providers: {
    generation: string;
    vision: string;
    evaluation: string;
    embedding: string;
  };
}

export interface SummarizeCostsResponse {
  per_cluster: number;
  cluster_count: number;
  total: number;
  provider: string;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
}

// --- Operations Monitor types ---

export interface CostDecisionEntry {
  id: number;
  trace_id: string | null;
  user_id: number;
  job_id: number | null;
  operation: string;
  provider: string;
  model: string;
  catalog_entry_id: number | null;
  catalog_match_tier: string | null;
  estimated_input_tokens: number | null;
  estimated_output_tokens: number | null;
  estimated_sparks: number | null;
  cost_per_input_token: number | null;
  cost_per_output_token: number | null;
  cost_per_call: number | null;
  platform_markup: number | null;
  billing_model: string | null;
  image_id: number | null;
  resource_id: number | null;
  request_snapshot: Record<string, unknown> | null;
  response_snapshot: Record<string, unknown> | null;
  status: string;
  error_message: string | null;
  idempotency_key: string | null;
  created_at: string;
  updated_at: string;
}

export interface DecisionListResponse {
  items: CostDecisionEntry[];
  total: number;
  skip: number;
  limit: number;
}

export interface TraceUsageRecord {
  id: number;
  user_id: number;
  operation: string;
  provider: string;
  model: string;
  input_tokens: number | null;
  output_tokens: number | null;
  raw_cost: number;
  charged_cost: number;
  cost_decision_id: number | null;
  delta_sparks: number | null;
  created_at: string;
}

export interface TracePipelineLog {
  id: number;
  category: string;
  message: string;
  provider: string | null;
  model: string | null;
  operation: string | null;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  success: boolean | null;
  created_at: string;
}

export interface TraceTransaction {
  id: number;
  amount: number;
  transaction_type: string;
  description: string;
  created_at: string;
}

export interface TraceResponse {
  trace_id: string;
  decisions: CostDecisionEntry[];
  usage_records: TraceUsageRecord[];
  pipeline_logs: TracePipelineLog[];
  transactions: TraceTransaction[];
}

// --- Scatter / Trend types ---

export interface ScatterPoint {
  estimated_sparks: number;
  actual_sparks: number;
  operation: string;
  provider: string;
  created_at: string;
}

export interface ScatterResponse {
  items: ScatterPoint[];
}

export interface TrendBucket {
  hour: string;
  total: number;
  by_type: Record<string, number>;
}

export interface TrendResponse {
  items: TrendBucket[];
  hours: number;
}
