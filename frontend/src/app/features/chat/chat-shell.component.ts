import { Component, inject, OnInit, OnDestroy, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatListModule } from '@angular/material/list';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDividerModule } from '@angular/material/divider';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { AuthService } from '../../core/services/auth.service';
import { SessionService } from '../../core/services/session.service';
import { WebSocketService } from '../../core/services/websocket.service';
import { SessionStore } from '../../core/stores/session.store';
import { SessionListItem } from '../../core/models';

import { DrawingPanelComponent } from './components/drawing-panel.component';
import { ChatPanelComponent } from './components/chat-panel.component';

@Component({
  selector: 'app-chat-shell',
  standalone: true,
  imports: [
    CommonModule,
    MatToolbarModule,
    MatButtonModule,
    MatIconModule,
    MatSidenavModule,
    MatListModule,
    MatTooltipModule,
    MatDividerModule,
    MatProgressSpinnerModule,
    DrawingPanelComponent,
    ChatPanelComponent,
  ],
  template: `
    <div class="chat-shell">
      <!-- Top Toolbar -->
      <mat-toolbar class="app-toolbar" color="primary">
        <button mat-icon-button (click)="sidenavOpen.set(!sidenavOpen())">
          <mat-icon>menu</mat-icon>
        </button>
        <span class="app-title">Shapy</span>
        <span class="spacer"></span>

        <!-- Connection Status -->
        <div class="connection-status" [class]="'status-' + store.wsStatus()">
          <span class="status-dot"></span>
          <span class="status-text">{{ store.wsStatus() }}</span>
        </div>

        <span class="user-email">{{ store.currentUserEmail() }}</span>
        <button mat-icon-button (click)="logout()" matTooltip="Logout">
          <mat-icon>logout</mat-icon>
        </button>
      </mat-toolbar>

      <!-- Main Content with Sidenav -->
      <mat-sidenav-container class="sidenav-container">
        <!-- Sidebar -->
        <mat-sidenav
          #sidenav
          [opened]="sidenavOpen()"
          mode="side"
          class="app-sidenav"
        >
          <div class="sidenav-header">
            <h3>Sessions</h3>
            <button
              mat-mini-fab
              color="primary"
              (click)="createNewSession()"
              [disabled]="isCreatingSession()"
              matTooltip="New Session"
            >
              @if (isCreatingSession()) {
                <mat-spinner diameter="20"></mat-spinner>
              } @else {
                <mat-icon>add</mat-icon>
              }
            </button>
          </div>

          <mat-divider></mat-divider>

          <mat-nav-list class="session-list">
            @if (isLoadingSessions()) {
              <div class="loading-sessions">
                <mat-spinner diameter="32"></mat-spinner>
              </div>
            } @else if (store.sessions().length === 0) {
              <div class="no-sessions">
                <mat-icon>chat_bubble_outline</mat-icon>
                <p>No sessions yet</p>
                <p class="hint">Create a new session to start</p>
              </div>
            } @else {
              @for (session of store.sessions(); track session.session_id) {
                <mat-list-item
                  [class.active]="session.session_id === store.currentSessionId()"
                  (click)="selectSession(session)"
                >
                  <mat-icon matListItemIcon>
                    {{ session.has_context ? 'description' : 'chat_bubble_outline' }}
                  </mat-icon>
                  <span matListItemTitle>{{ formatSessionDate(session.created_at) }}</span>
                  <span matListItemLine>
                    {{ session.has_context ? session.object_count + ' objects' : 'No drawing' }}
                  </span>
                  <button
                    mat-icon-button
                    matListItemMeta
                    (click)="deleteSession(session, $event)"
                    matTooltip="Delete session"
                  >
                    <mat-icon>delete_outline</mat-icon>
                  </button>
                </mat-list-item>
              }
            }
          </mat-nav-list>
        </mat-sidenav>

        <!-- Main Content -->
        <mat-sidenav-content class="main-content">
          @if (!store.currentSessionId()) {
            <div class="no-session-selected">
              <mat-icon class="big-icon">forum</mat-icon>
              <h2>Welcome to Shapy</h2>
              <p>Select a session or create a new one to start chatting</p>
              <button mat-raised-button color="primary" (click)="createNewSession()">
                <mat-icon>add</mat-icon>
                New Session
              </button>
            </div>
          } @else {
            <div class="workspace">
              <!-- Split Pane -->
              <div class="split-pane">
                <!-- Left: Drawing Panel -->
                <div class="panel drawing-panel" [style.flex-basis.%]="drawingPanelWidth()">
                  <app-drawing-panel></app-drawing-panel>
                </div>

                <!-- Resizer -->
                <div
                  class="resizer"
                  (mousedown)="startResize($event)"
                ></div>

                <!-- Right: Chat Panel -->
                <div class="panel chat-panel">
                  <app-chat-panel></app-chat-panel>
                </div>
              </div>
            </div>
          }
        </mat-sidenav-content>
      </mat-sidenav-container>
    </div>
  `,
  styles: [`
    .chat-shell {
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }

    .app-toolbar {
      flex-shrink: 0;
      z-index: 100;
    }

    .app-title {
      font-weight: 500;
      margin-left: 8px;
    }

    .spacer {
      flex: 1 1 auto;
    }

    .connection-status {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      border-radius: 16px;
      font-size: 12px;
      margin-right: 16px;
      background: rgba(255, 255, 255, 0.15);
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }

    .status-disconnected .status-dot { background: #9e9e9e; }
    .status-connecting .status-dot { background: #ff9800; animation: pulse 1s infinite; }
    .status-connected .status-dot { background: #4caf50; }
    .status-error .status-dot { background: #f44336; }

    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.5; }
    }

    .user-email {
      margin-right: 8px;
      font-size: 14px;
      opacity: 0.9;
    }

    .sidenav-container {
      flex: 1;
      height: calc(100vh - 64px);
    }

    .app-sidenav {
      width: 280px;
      background: #fff;
      border-right: 1px solid #e8e8e8;
    }

    .sidenav-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px;
      background: #fafafa;
    }

    .sidenav-header h3 {
      margin: 0;
      font-size: 14px;
      font-weight: 600;
      color: #444;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .session-list {
      padding-top: 0;
    }

    .session-list mat-list-item {
      cursor: pointer;
      margin: 2px 8px;
      border-radius: 4px;
      transition: background 0.15s ease;
    }

    .session-list mat-list-item.active {
      background: #673ab7;
      color: white;
    }

    .session-list mat-list-item.active span,
    .session-list mat-list-item.active mat-icon {
      color: white !important;
    }

    .session-list mat-list-item.active [matListItemLine] {
      color: rgba(255, 255, 255, 0.8) !important;
    }

    .session-list mat-list-item:hover:not(.active) {
      background: rgba(103, 58, 183, 0.06);
    }

    .session-list mat-list-item.active button {
      color: rgba(255, 255, 255, 0.9);
    }

    .session-list mat-list-item.active button:hover {
      background: rgba(255, 255, 255, 0.15);
    }

    .loading-sessions, .no-sessions {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 48px 16px;
      color: #666;
    }

    .no-sessions mat-icon {
      font-size: 48px;
      width: 48px;
      height: 48px;
      color: #ccc;
    }

    .no-sessions p {
      margin: 8px 0 0;
    }

    .no-sessions .hint {
      font-size: 12px;
      color: #999;
    }

    .main-content {
      background: #f0f0f0;
      height: 100%;
      overflow: hidden;
    }

    .no-session-selected {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100%;
      color: #666;
      text-align: center;
      padding: 24px;
    }

    .no-session-selected .big-icon {
      font-size: 80px;
      width: 80px;
      height: 80px;
      color: #ddd;
      margin-bottom: 16px;
    }

    .no-session-selected h2 {
      margin: 0 0 8px;
      color: #333;
    }

    .no-session-selected p {
      margin: 0 0 24px;
    }

    .workspace {
      height: 100%;
    }

    .split-pane {
      height: 100%;
      display: flex;
    }

    .panel {
      height: 100%;
      overflow: hidden;
    }

    .drawing-panel {
      min-width: 300px;
      background: #fff;
      border-right: 1px solid #e0e0e0;
      flex-shrink: 0;
    }

    .chat-panel {
      flex: 1;
      min-width: 250px;
      background: #fff;
    }

    .resizer {
      width: 6px;
      background: #e0e0e0;
      cursor: col-resize;
      flex-shrink: 0;
      transition: background 0.2s;
    }

    .resizer:hover {
      background: #673ab7;
    }
  `],
})
export class ChatShellComponent implements OnInit, OnDestroy {
  readonly store = inject(SessionStore);
  private readonly authService = inject(AuthService);
  private readonly sessionService = inject(SessionService);
  private readonly wsService = inject(WebSocketService);
  private readonly router = inject(Router);

  readonly sidenavOpen = signal(true);
  readonly isLoadingSessions = signal(false);
  readonly isCreatingSession = signal(false);
  readonly drawingPanelWidth = signal(65);

  private isResizing = false;

  ngOnInit(): void {
    this.loadSessions();
  }

  ngOnDestroy(): void {
    this.wsService.disconnect();
  }

  loadSessions(): void {
    this.isLoadingSessions.set(true);
    this.sessionService.listSessions().subscribe({
      next: () => this.isLoadingSessions.set(false),
      error: () => this.isLoadingSessions.set(false),
    });
  }

  createNewSession(): void {
    this.isCreatingSession.set(true);
    this.sessionService.createSession().subscribe({
      next: (response) => {
        this.isCreatingSession.set(false);
        this.selectSessionById(response.session_id);
      },
      error: () => this.isCreatingSession.set(false),
    });
  }

  selectSession(session: SessionListItem): void {
    this.selectSessionById(session.session_id);
  }

  selectSessionById(sessionId: string): void {
    if (this.store.currentSessionId() === sessionId) {
      return;
    }

    this.wsService.disconnect();
    this.store.setCurrentSession(sessionId);
    this.store.clearChatState();
    this.store.clearDrawingState();

    const token = this.authService.accessToken;
    if (token) {
      this.wsService.connect(sessionId, token);
    }

    this.loadSessionContext(sessionId);
  }

  loadSessionContext(sessionId: string): void {
    this.sessionService.getContext(sessionId).subscribe({
      next: (response) => {
        this.store.setDrawingContext(response.objects, response.metadata);
      },
      error: () => {
        this.store.clearDrawingState();
      },
    });
  }

  deleteSession(session: SessionListItem, event: Event): void {
    event.stopPropagation();

    if (confirm('Delete this session? This cannot be undone.')) {
      this.sessionService.deleteSession(session.session_id).subscribe();
    }
  }

  formatSessionDate(dateStr: string): string {
    const date = new Date(dateStr);
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();

    if (isToday) {
      return 'Today ' + date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    }

    return date.toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  startResize(event: MouseEvent): void {
    this.isResizing = true;
    event.preventDefault();

    const container = (event.target as HTMLElement).parentElement;
    if (!container) return;

    const containerWidth = container.getBoundingClientRect().width;
    const startX = event.clientX;
    const startPercent = this.drawingPanelWidth();

    const onMouseMove = (e: MouseEvent) => {
      if (!this.isResizing) return;
      const diff = e.clientX - startX;
      const percentChange = (diff / containerWidth) * 100;
      const newPercent = Math.max(40, Math.min(startPercent + percentChange, 75));
      this.drawingPanelWidth.set(newPercent);
    };

    const onMouseUp = () => {
      this.isResizing = false;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }

  logout(): void {
    this.wsService.disconnect();
    this.authService.logout();
  }
}
