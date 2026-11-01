import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { readApiError } from '../../api-error';
import { DashboardStats, ReviewSummary } from '../../models';
import { ReviewApi } from '../../review-api';
import {
  categoryLabel,
  findingCounts,
  sourceLabel,
  statusBadgeClass,
  statusLabel,
} from '../../review-format';

@Component({
  selector: 'app-dashboard',
  imports: [RouterLink, DatePipe],
  templateUrl: './dashboard.html',
})
export class DashboardPage {
  private readonly api = inject(ReviewApi);

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly stats = signal<DashboardStats | null>(null);
  protected readonly recent = signal<ReviewSummary[]>([]);
  protected readonly categoryLabel = categoryLabel;
  protected readonly statusLabel = statusLabel;
  protected readonly statusBadgeClass = statusBadgeClass;
  protected readonly sourceLabel = sourceLabel;
  protected readonly findingCounts = findingCounts;

  constructor() {
    void this.load();
  }

  protected categoryEntries(stats: DashboardStats): { category: string; count: number }[] {
    return Object.entries(stats.findings_by_category)
      .filter(([, count]) => count > 0)
      .map(([category, count]) => ({ category, count }));
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [stats, recent] = await Promise.all([
        firstValueFrom(this.api.stats()),
        firstValueFrom(this.api.list(6, 0)),
      ]);
      this.stats.set(stats);
      this.recent.set(recent.items);
    } catch (error) {
      this.error.set(readApiError(error).message);
    } finally {
      this.loading.set(false);
    }
  }
}
