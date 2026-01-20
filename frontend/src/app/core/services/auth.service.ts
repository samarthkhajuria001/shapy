import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, tap, catchError, throwError, BehaviorSubject } from 'rxjs';
import { environment } from '../../../environments/environment';
import { SessionStore } from '../stores/session.store';
import {
  UserLoginRequest,
  UserRegisterRequest,
  TokenResponse,
  UserResponse,
} from '../models';

const TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly store = inject(SessionStore);

  private readonly isRefreshing$ = new BehaviorSubject<boolean>(false);

  get accessToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  }

  get refreshToken(): string | null {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  }

  get isLoggedIn(): boolean {
    return !!this.accessToken;
  }

  register(request: UserRegisterRequest): Observable<UserResponse> {
    return this.http.post<UserResponse>(`${environment.apiUrl}/auth/register`, request);
  }

  login(request: UserLoginRequest): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(`${environment.apiUrl}/auth/login`, request).pipe(
      tap((response) => this.handleAuthSuccess(response)),
      catchError((error) => {
        this.clearTokens();
        return throwError(() => error);
      })
    );
  }

  logout(): void {
    const refreshToken = this.refreshToken;

    if (refreshToken) {
      this.http
        .post(`${environment.apiUrl}/auth/logout`, { refresh_token: refreshToken })
        .subscribe({
          complete: () => this.handleLogout(),
          error: () => this.handleLogout(),
        });
    } else {
      this.handleLogout();
    }
  }

  refreshAccessToken(): Observable<TokenResponse> {
    const refreshToken = this.refreshToken;

    if (!refreshToken) {
      return throwError(() => new Error('No refresh token available'));
    }

    this.isRefreshing$.next(true);

    return this.http
      .post<TokenResponse>(`${environment.apiUrl}/auth/refresh`, {
        refresh_token: refreshToken,
      })
      .pipe(
        tap((response) => {
          this.setTokens(response.access_token, response.refresh_token);
          this.isRefreshing$.next(false);
        }),
        catchError((error) => {
          this.isRefreshing$.next(false);
          this.handleLogout();
          return throwError(() => error);
        })
      );
  }

  initializeAuth(): void {
    const token = this.accessToken;
    if (token) {
      const payload = this.parseJwt(token);
      if (payload && !this.isTokenExpired(payload)) {
        this.store.setAuthenticated(payload.sub, payload.email || '');
      } else {
        this.refreshAccessToken().subscribe({
          next: () => {
            const newToken = this.accessToken;
            if (newToken) {
              const newPayload = this.parseJwt(newToken);
              if (newPayload) {
                this.store.setAuthenticated(newPayload.sub, newPayload.email || '');
              }
            }
          },
          error: () => this.clearTokens(),
        });
      }
    }
  }

  private handleAuthSuccess(response: TokenResponse): void {
    this.setTokens(response.access_token, response.refresh_token);

    const payload = this.parseJwt(response.access_token);
    if (payload) {
      this.store.setAuthenticated(payload.sub, payload.email || '');
    }
  }

  private handleLogout(): void {
    this.clearTokens();
    this.store.clearAuth();
    this.router.navigate(['/login']);
  }

  private setTokens(accessToken: string, refreshToken: string): void {
    localStorage.setItem(TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  }

  private clearTokens(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  }

  private parseJwt(token: string): JwtPayload | null {
    try {
      const base64Url = token.split('.')[1];
      const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
      const jsonPayload = decodeURIComponent(
        atob(base64)
          .split('')
          .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
          .join('')
      );
      return JSON.parse(jsonPayload);
    } catch {
      return null;
    }
  }

  private isTokenExpired(payload: JwtPayload): boolean {
    if (!payload.exp) {
      return true;
    }
    const expirationDate = new Date(payload.exp * 1000);
    const now = new Date();
    // Consider token expired 1 minute before actual expiration
    return expirationDate.getTime() - now.getTime() < 60000;
  }
}

interface JwtPayload {
  sub: string;
  email?: string;
  exp?: number;
  type?: string;
}
