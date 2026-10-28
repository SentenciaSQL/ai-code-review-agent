import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';

import { WorkspaceState } from './workspace-state';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
})
export class App {
  protected readonly workspace = inject(WorkspaceState);
  protected readonly navOpen = signal(false);

  constructor() {
    const router = inject(Router);
    const destroyRef = inject(DestroyRef);
    router.events
      .pipe(
        filter((event) => event instanceof NavigationEnd),
        takeUntilDestroyed(destroyRef),
      )
      .subscribe(() => this.navOpen.set(false));
    void this.workspace.refresh();
  }

  protected closeNav(): void {
    this.navOpen.set(false);
  }

  protected toggleNav(): void {
    this.navOpen.update((open) => !open);
  }
}
