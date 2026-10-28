import { DatePipe } from '@angular/common';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { readApiError } from '../../api-error';
import { Finding, ReviewDetail } from '../../models';
import { ReviewApi } from '../../review-api';
import {
  SEVERITIES,
  categoryLabel,
  findingCopyText,
  lineReference,
  severityAccentClass,
  severityBadgeClass,
  severityLabel,
  sourceLabel,
  statusBadgeClass,
  statusLabel,
} from '../../review-format';

@Component({
  selector: 'app-review-detail',
  imports: [DatePipe, RouterLink],
  templateUrl: './review-detail.html',
})
export class ReviewDetailPage {
  private readonly api = inject(ReviewApi);
  private readonly router = inject(Router);

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly review = signal<ReviewDetail | null>(null);
  protected readonly severity = signal<string>('all');
  protected readonly category = signal<string>('all');
  protected readonly file = signal<string>('all');
  protected readonly groupBy = signal<'severity' | 'category'>('severity');
  protected readonly expanded = signal<ReadonlySet<string>>(new Set());
  protected readonly copiedId = signal<string | null>(null);
  protected readonly copyError = signal<string | null>(null);
  protected readonly exportError = signal<string | null>(null);
  protected readonly confirmDelete = signal(false);
  protected readonly deleting = signal(false);
  protected readonly severities = SEVERITIES;
  protected readonly severityLabel = severityLabel;
  protected readonly categoryLabel = categoryLabel;
  protected readonly statusLabel = statusLabel;
  protected readonly statusBadgeClass = statusBadgeClass;
  protected readonly severityBadgeClass = severityBadgeClass;
  protected readonly severityAccentClass = severityAccentClass;
  protected readonly sourceLabel = sourceLabel;
  protected readonly lineReference = lineReference;

  protected readonly filtered = computed(() => {
    const review = this.review();
    if (!review) {
      return [];
    }
    return review.findings.filter((finding) => {
      if (this.severity() !== 'all' && finding.severity !== this.severity()) {
        return false;
      }
      if (this.category() !== 'all' && finding.category !== this.category()) {
        return false;
      }
      if (this.file() !== 'all' && (finding.file_path ?? 'Unknown file') !== this.file()) {
        return false;
      }
      return true;
    });
  });

  protected readonly groups = computed(() => {
    const mode = this.groupBy();
    const buckets = new Map<string, Finding[]>();
    for (const finding of this.filtered()) {
      const key = mode === 'category' ? finding.category : finding.severity;
      const current = buckets.get(key) ?? [];
      current.push(finding);
      buckets.set(key, current);
    }
    const order =
      mode === 'category'
        ? ['bug', 'security', 'performance', 'error_handling', 'concurrency', 'maintainability', 'code_quality']
        : [...SEVERITIES];
    return [...buckets.entries()]
      .sort((left, right) => {
        const leftIndex = order.indexOf(left[0] as (typeof order)[number]);
        const rightIndex = order.indexOf(right[0] as (typeof order)[number]);
        return (leftIndex === -1 ? 99 : leftIndex) - (rightIndex === -1 ? 99 : rightIndex);
      })
      .map(([key, items]) => ({
        key,
        label: mode === 'category' ? categoryLabel(key) : severityLabel(key),
        items,
      }));
  });

  protected readonly categories = computed(() => {
    const review = this.review();
    if (!review) {
      return [];
    }
    return [...new Set(review.findings.map((finding) => finding.category))];
  });

  protected readonly files = computed(() => {
    const review = this.review();
    if (!review) {
      return [];
    }
    return [...new Set(review.findings.map((finding) => finding.file_path ?? 'Unknown file'))];
  });

  protected readonly severityTotals = computed(() => {
    const totals: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const finding of this.review()?.findings ?? []) {
      totals[finding.severity] = (totals[finding.severity] ?? 0) + 1;
    }
    return totals;
  });

  constructor() {
    const route = inject(ActivatedRoute);
    const destroyRef = inject(DestroyRef);
    route.paramMap.pipe(takeUntilDestroyed(destroyRef)).subscribe((params) => {
      const id = params.get('id');
      if (id) {
        void this.load(id);
      }
    });
  }

  protected setSeverity(value: string): void {
    this.severity.set(this.severity() === value ? 'all' : value);
  }

  protected clearFilters(): void {
    this.severity.set('all');
    this.category.set('all');
    this.file.set('all');
  }

  protected filtersActive(): boolean {
    return this.severity() !== 'all' || this.category() !== 'all' || this.file() !== 'all';
  }

  protected isOpen(id: string): boolean {
    return this.expanded().has(id);
  }

  protected toggle(id: string): void {
    const next = new Set(this.expanded());
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    this.expanded.set(next);
  }

  protected confidence(finding: Finding): string {
    return `${Math.round(finding.confidence * 100)}%`;
  }

  protected async copy(finding: Finding): Promise<void> {
    this.copyError.set(null);
    try {
      await navigator.clipboard.writeText(findingCopyText(finding));
      this.copiedId.set(finding.id);
    } catch {
      this.copyError.set('The browser blocked clipboard access for this finding.');
    }
  }

  protected async download(format: 'json' | 'markdown'): Promise<void> {
    const review = this.review();
    if (!review) {
      return;
    }
    this.exportError.set(null);
    try {
      const blob = await firstValueFrom(this.api.export(review.id, format));
      const extension = format === 'json' ? 'json' : 'md';
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `patchline-${review.id}.${extension}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      this.exportError.set(readApiError(error).message);
    }
  }

  protected async remove(): Promise<void> {
    const review = this.review();
    if (!review) {
      return;
    }
    this.deleting.set(true);
    this.error.set(null);
    try {
      await firstValueFrom(this.api.delete(review.id));
      await this.router.navigate(['/history']);
    } catch (error) {
      this.error.set(readApiError(error).message);
      this.deleting.set(false);
    }
  }

  private async load(id: string): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    this.confirmDelete.set(false);
    this.clearFilters();
    try {
      this.review.set(await firstValueFrom(this.api.get(id)));
    } catch (error) {
      this.review.set(null);
      this.error.set(readApiError(error).message);
    } finally {
      this.loading.set(false);
    }
  }
}
