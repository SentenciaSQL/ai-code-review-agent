import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { readApiError } from './api-error';
import { HealthResponse } from './models';
import { ReviewApi } from './review-api';

@Injectable({ providedIn: 'root' })
export class WorkspaceState {
  private readonly api = inject(ReviewApi);

  readonly health = signal<HealthResponse | null>(null);
  readonly healthError = signal<string | null>(null);
  readonly loaded = signal(false);

  async refresh(): Promise<void> {
    try {
      const health = await firstValueFrom(this.api.health());
      this.health.set(health);
      this.healthError.set(null);
    } catch (error) {
      this.health.set(null);
      this.healthError.set(readApiError(error).message);
    } finally {
      this.loaded.set(true);
    }
  }
}
