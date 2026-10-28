import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  DashboardStats,
  HealthResponse,
  ReviewDetail,
  ReviewList,
} from './models';

@Injectable({ providedIn: 'root' })
export class ReviewApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api';

  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.base}/health`);
  }

  stats(): Observable<DashboardStats> {
    return this.http.get<DashboardStats>(`${this.base}/reviews/stats`);
  }

  list(limit: number, offset: number): Observable<ReviewList> {
    const params = new HttpParams().set('limit', limit).set('offset', offset);
    return this.http.get<ReviewList>(`${this.base}/reviews`, { params });
  }

  get(id: string): Observable<ReviewDetail> {
    return this.http.get<ReviewDetail>(`${this.base}/reviews/${id}`);
  }

  createDiff(body: { title: string | null; diff: string }): Observable<ReviewDetail> {
    return this.http.post<ReviewDetail>(`${this.base}/reviews/diff`, body);
  }

  createGitHub(body: {
    title: string | null;
    repository_url: string;
    pull_request_number: number | null;
  }): Observable<ReviewDetail> {
    return this.http.post<ReviewDetail>(`${this.base}/reviews/github`, body);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/reviews/${id}`);
  }

  export(id: string, format: 'json' | 'markdown'): Observable<Blob> {
    const params = new HttpParams().set('format', format);
    return this.http.get(`${this.base}/reviews/${id}/export`, {
      params,
      responseType: 'blob',
    });
  }
}
