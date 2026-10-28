export type Severity = 'critical' | 'high' | 'medium' | 'low';
export type Category =
  | 'bug'
  | 'security'
  | 'performance'
  | 'error_handling'
  | 'concurrency'
  | 'maintainability'
  | 'code_quality';
export type FindingKind = 'finding' | 'suggestion';
export type ReviewStatus = 'processing' | 'completed' | 'failed';
export type SourceType = 'diff' | 'github';

export interface SeverityCounts {
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface Finding {
  id: string;
  title: string;
  explanation: string;
  severity: Severity;
  category: Category;
  kind: FindingKind;
  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  code_snippet: string | null;
  recommended_fix: string;
  confidence: number;
  suggested_patch: string | null;
  insufficient_context: boolean;
}

export interface ReviewFile {
  path: string;
  status: string;
  additions: number;
  deletions: number;
  binary: boolean;
  omitted: boolean;
}

export interface PullRequestInfo {
  owner: string;
  repo: string;
  number: number;
  url: string;
  title: string;
  head_sha: string | null;
  base_ref: string | null;
  author: string | null;
}

export interface ReviewMetadata {
  prompt_version: string | null;
  files: ReviewFile[];
  pull_request: PullRequestInfo | null;
  usage: { prompt_tokens: number | null; completion_tokens: number | null } | null;
  omitted_files: string[];
}

export interface ReviewSummary {
  id: string;
  title: string;
  source_type: SourceType;
  source_ref: string | null;
  status: ReviewStatus;
  summary: string | null;
  finding_count: number;
  suggestion_count: number;
  severity_counts: SeverityCounts;
  provider: string | null;
  model: string | null;
  created_at: string;
  updated_at: string;
  error_message: string | null;
}

export interface ReviewList {
  items: ReviewSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ReviewDetail {
  id: string;
  title: string;
  source_type: SourceType;
  source_ref: string | null;
  status: ReviewStatus;
  summary: string | null;
  context_limitations: string | null;
  findings: Finding[];
  provider: string | null;
  model: string | null;
  prompt_version: string | null;
  error_message: string | null;
  metadata: ReviewMetadata;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface DashboardStats {
  total_reviews: number;
  completed_reviews: number;
  failed_reviews: number;
  processing_reviews: number;
  total_findings: number;
  total_suggestions: number;
  findings_by_severity: SeverityCounts;
  findings_by_category: Record<string, number>;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  app_name: string;
  version: string;
  database: 'ok' | 'error';
  llm_provider: string;
  llm_model: string;
  llm_configured: boolean;
  github_token_configured: boolean;
  max_diff_bytes: number;
  max_diff_files: number;
  max_findings: number;
}

export interface ApiError {
  message: string;
  code?: string;
  reviewId?: string;
}
