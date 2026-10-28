import { Routes } from '@angular/router';

import { DashboardPage } from './pages/dashboard/dashboard';
import { HistoryPage } from './pages/history/history';
import { NewReviewPage } from './pages/new-review/new-review';
import { ReviewDetailPage } from './pages/review-detail/review-detail';

export const routes: Routes = [
  { path: '', component: DashboardPage, title: 'Dashboard · Patchline' },
  { path: 'reviews/new', component: NewReviewPage, title: 'New review · Patchline' },
  { path: 'reviews/:id', component: ReviewDetailPage, title: 'Review · Patchline' },
  { path: 'history', component: HistoryPage, title: 'History · Patchline' },
  { path: '**', redirectTo: '' },
];
