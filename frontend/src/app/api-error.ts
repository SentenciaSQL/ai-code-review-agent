import { HttpErrorResponse } from '@angular/common/http';

import { ApiError } from './models';

export function readApiError(error: unknown): ApiError {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0) {
      return {
        message: 'Cannot reach the review API. Start the backend, then reload this page.',
      };
    }
    const body = error.error;
    if (body instanceof Blob) {
      return { message: `The request failed (${error.status}).` };
    }
    if (body && typeof body === 'object') {
      const detail = body.detail;
      const code = typeof body.code === 'string' ? body.code : undefined;
      const reviewId = typeof body.review_id === 'string' ? body.review_id : undefined;
      if (typeof detail === 'string' && detail.trim()) {
        return { message: detail, code, reviewId };
      }
      if (Array.isArray(detail)) {
        const message = detail
          .map((item) => (item && typeof item.msg === 'string' ? item.msg : 'Invalid value'))
          .join(' ');
        return { message, code, reviewId };
      }
    }
    return { message: `The request failed (${error.status}).` };
  }
  return { message: 'Something went wrong before the review could be saved.' };
}
