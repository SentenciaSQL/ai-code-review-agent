import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { readApiError } from '../../api-error';
import { ReviewSummary } from '../../models';
import { ReviewApi } from '../../review-api';
import { findingCounts, sourceLabel, statusBadgeClass, statusLabel } from '../../review-format';

@Component({
  selector: 'app-history',
  imports: [DatePipe, RouterLink],
  templateUrl: './history.html',
})
export class HistoryPage {
  private readonly api = inject(ReviewApi);
  private readonly limit = 20;

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly items = signal<ReviewSummary[]>([]);
  protected readonly total = signal(0);
  protected readonly offset = signal(0);
  protected readonly pendingDelete = signal<string | null>(null);
  protected readonly deleting = signal(false);
  protected readonly statusLabel = statusLabel;
  protected readonly statusBadgeClass = statusBadgeClass;
  protected readonly sourceLabel = sourceLabel;
  protected readonly findingCounts = findingCounts;

  protected readonly pageStart = computed(() => (this.total() === 0 ? 0 : this.offset() + 1));
  protected readonly pageEnd = computed(() => Math.min(this.offset() + this.items().length, this.total()));

  constructor() {
    void this.load();
  }

  protected async previous(): Promise<void> {
    this.offset.set(Math.max(0, this.offset() - this.limit));
    await this.load();
  }

  protected async next(): Promise<void> {
    this.offset.set(this.offset() + this.limit);
    await this.load();
  }

  protected async remove(id: string): Promise<void> {
    this.deleting.set(true);
    this.error.set(null);
    try {
      await firstValueFrom(this.api.delete(id));
      this.pendingDelete.set(null);
      if (this.items().length === 1 && this.offset() > 0) {
        this.offset.set(Math.max(0, this.offset() - this.limit));
      }
      await this.load();
    } catch (error) {
      this.error.set(readApiError(error).message);
    } finally {
      this.deleting.set(false);
    }
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const page = await firstValueFrom(this.api.list(this.limit, this.offset()));
      this.items.set(page.items);
      this.total.set(page.total);
    } catch (error) {
      this.error.set(readApiError(error).message);
    } finally {
      this.loading.set(false);
    }
  }
}
