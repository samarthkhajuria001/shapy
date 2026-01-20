import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { SessionStore } from '../stores/session.store';
import {
  SessionCreateResponse,
  SessionStatusResponse,
  SessionListResponse,
  ContextUpdateRequest,
  ContextUpdateResponse,
  ContextGetResponse,
  DrawingObject,
} from '../models';

@Injectable({ providedIn: 'root' })
export class SessionService {
  private readonly http = inject(HttpClient);
  private readonly store = inject(SessionStore);

  createSession(): Observable<SessionCreateResponse> {
    return this.http.post<SessionCreateResponse>(`${environment.apiUrl}/session`, {}).pipe(
      tap((response) => {
        this.store.addSession({
          session_id: response.session_id,
          created_at: response.created_at,
          has_context: false,
          object_count: 0,
        });
      })
    );
  }

  getSession(sessionId: string): Observable<SessionStatusResponse> {
    return this.http.get<SessionStatusResponse>(`${environment.apiUrl}/session/${sessionId}`);
  }

  listSessions(): Observable<SessionListResponse> {
    return this.http.get<SessionListResponse>(`${environment.apiUrl}/session`).pipe(
      tap((response) => {
        this.store.setSessions(response.sessions);
      })
    );
  }

  deleteSession(sessionId: string): Observable<void> {
    return this.http.delete<void>(`${environment.apiUrl}/session/${sessionId}`).pipe(
      tap(() => {
        this.store.removeSession(sessionId);
      })
    );
  }

  updateContext(sessionId: string, objects: DrawingObject[]): Observable<ContextUpdateResponse> {
    const request: ContextUpdateRequest = { objects };
    return this.http.put<ContextUpdateResponse>(
      `${environment.apiUrl}/session/${sessionId}/context`,
      request
    );
  }

  getContext(sessionId: string): Observable<ContextGetResponse> {
    return this.http.get<ContextGetResponse>(`${environment.apiUrl}/session/${sessionId}/context`);
  }
}
