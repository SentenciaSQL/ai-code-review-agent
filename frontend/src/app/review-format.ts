import { Category, Finding, ReviewSummary, Severity } from './models';

export const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'low'];

export const CATEGORY_LABELS: Record<Category, string> = {
  bug: 'Bugs and logic',
  security: 'Security',
  performance: 'Performance',
  error_handling: 'Error handling',
  concurrency: 'Concurrency and resources',
  maintainability: 'Maintainability',
  code_quality: 'Code quality',
};

export function severityLabel(severity: string): string {
  if (!severity) {
    return 'Unknown';
  }
  return severity.charAt(0).toUpperCase() + severity.slice(1);
}

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category as Category] ?? category.replaceAll('_', ' ');
}

export function statusLabel(status: string): string {
  switch (status) {
    case 'completed':
      return 'Completed';
    case 'failed':
      return 'Failed';
    case 'processing':
      return 'In progress';
    default:
      return status;
  }
}

export function sourceLabel(review: { source_type: string; source_ref: string | null }): string {
  if (review.source_type === 'github') {
    return review.source_ref ? `GitHub ${review.source_ref}` : 'GitHub pull request';
  }
  return 'Pasted diff';
}

export function lineReference(finding: Pick<Finding, 'file_path' | 'line_start' | 'line_end'>): string {
  const file = finding.file_path ?? 'Unknown file';
  if (finding.line_start == null) {
    return file;
  }
  if (finding.line_end == null || finding.line_end === finding.line_start) {
    return `${file}:${finding.line_start}`;
  }
  return `${file}:${finding.line_start}-${finding.line_end}`;
}

export function severityBadgeClass(severity: string): string {
  switch (severity) {
    case 'critical':
      return 'bg-red-50 text-red-900 ring-red-200';
    case 'high':
      return 'bg-orange-50 text-orange-950 ring-orange-200';
    case 'medium':
      return 'bg-amber-50 text-amber-950 ring-amber-200';
    case 'low':
      return 'bg-sky-50 text-sky-950 ring-sky-200';
    default:
      return 'bg-stone-100 text-stone-800 ring-stone-200';
  }
}

export function severityAccentClass(severity: string): string {
  switch (severity) {
    case 'critical':
      return 'border-l-red-600';
    case 'high':
      return 'border-l-orange-500';
    case 'medium':
      return 'border-l-amber-500';
    case 'low':
      return 'border-l-sky-600';
    default:
      return 'border-l-stone-400';
  }
}

export function statusBadgeClass(status: string): string {
  switch (status) {
    case 'completed':
      return 'bg-emerald-50 text-emerald-900 ring-emerald-200';
    case 'failed':
      return 'bg-red-50 text-red-900 ring-red-200';
    default:
      return 'bg-amber-50 text-amber-950 ring-amber-200';
  }
}

export function findingCounts(review: ReviewSummary): string {
  const parts: string[] = [];
  const counts = review.severity_counts;
  if (counts.critical) {
    parts.push(`${counts.critical} critical`);
  }
  if (counts.high) {
    parts.push(`${counts.high} high`);
  }
  if (counts.medium) {
    parts.push(`${counts.medium} medium`);
  }
  if (counts.low) {
    parts.push(`${counts.low} low`);
  }
  if (review.suggestion_count) {
    parts.push(`${review.suggestion_count} suggestions`);
  }
  return parts.join(' · ');
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function findingCopyText(finding: Finding): string {
  const lines = [
    `${severityLabel(finding.severity)} ${finding.kind}: ${finding.title}`,
    `Location: ${lineReference(finding)}`,
    `Category: ${categoryLabel(finding.category)}`,
    `Confidence: ${Math.round(finding.confidence * 100)}%`,
  ];
  if (finding.insufficient_context) {
    lines.push('Context: the model reported that the diff is not sufficient for a reliable determination.');
  }
  lines.push('', finding.explanation, '', 'Recommended fix:', finding.recommended_fix);
  if (finding.code_snippet) {
    lines.push('', 'Snippet:', finding.code_snippet);
  }
  if (finding.suggested_patch) {
    lines.push('', 'Suggested patch:', finding.suggested_patch);
  }
  return lines.join('\n');
}
