import { Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { readApiError } from '../../api-error';
import { ReviewApi } from '../../review-api';
import { formatBytes } from '../../review-format';
import { WorkspaceState } from '../../workspace-state';

@Component({
  selector: 'app-new-review',
  templateUrl: './new-review.html',
})
export class NewReviewPage {
  private readonly api = inject(ReviewApi);
  private readonly router = inject(Router);
  protected readonly workspace = inject(WorkspaceState);

  protected readonly mode = signal<'diff' | 'github'>('diff');
  protected readonly title = signal('');
  protected readonly diffText = signal('');
  protected readonly repositoryUrl = signal('');
  protected readonly pullRequestNumber = signal('');
  protected readonly submitting = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly formatBytes = formatBytes;

  protected readonly diffBytes = computed(() => new TextEncoder().encode(this.diffText()).length);
  protected readonly maxDiffBytes = computed(() => this.workspace.health()?.max_diff_bytes ?? 100000);

  protected onTitle(event: Event): void {
    this.title.set(this.value(event));
  }

  protected onDiff(event: Event): void {
    this.diffText.set(this.value(event));
  }

  protected onRepository(event: Event): void {
    this.repositoryUrl.set(this.value(event));
  }

  protected onPullRequest(event: Event): void {
    this.pullRequestNumber.set(this.value(event));
  }

  protected async start(event: Event): Promise<void> {
    event.preventDefault();
    if (this.submitting()) {
      return;
    }
    this.error.set(null);
    const title = this.title().trim() || null;

    if (this.mode() === 'diff') {
      if (!this.diffText().trim()) {
        this.error.set('Paste a unified Git diff before starting the review.');
        return;
      }
      if (this.diffBytes() > this.maxDiffBytes()) {
        this.error.set(`The diff is larger than the configured limit of ${formatBytes(this.maxDiffBytes())}.`);
        return;
      }
      await this.submit(() =>
        this.api.createDiff({
          title,
          diff: this.diffText(),
        }),
      );
      return;
    }

    if (!this.repositoryUrl().trim()) {
      this.error.set('Enter a GitHub repository URL or a pull request URL.');
      return;
    }
    const rawNumber = this.pullRequestNumber().trim();
    let pullRequestNumber: number | null = null;
    if (rawNumber) {
      if (!/^\d+$/.test(rawNumber) || Number(rawNumber) < 1) {
        this.error.set('The pull request number must be a positive integer.');
        return;
      }
      pullRequestNumber = Number(rawNumber);
    }
    await this.submit(() =>
      this.api.createGitHub({
        title,
        repository_url: this.repositoryUrl().trim(),
        pull_request_number: pullRequestNumber,
      }),
    );
  }

  private async submit(request: () => ReturnType<ReviewApi['createDiff']>): Promise<void> {
    this.submitting.set(true);
    try {
      const review = await firstValueFrom(request());
      await this.router.navigate(['/reviews', review.id]);
    } catch (error) {
      const parsed = readApiError(error);
      if (parsed.reviewId) {
        await this.router.navigate(['/reviews', parsed.reviewId]);
        return;
      }
      this.error.set(parsed.message);
    } finally {
      this.submitting.set(false);
    }
  }

  private value(event: Event): string {
    const target = event.target;
    return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement ? target.value : '';
  }
}
