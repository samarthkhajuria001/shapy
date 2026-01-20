import { Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { AuthService } from '../../core/services/auth.service';
import { SessionStore } from '../../core/stores/session.store';

@Component({
  selector: 'app-chat-shell',
  standalone: true,
  imports: [
    CommonModule,
    MatToolbarModule,
    MatButtonModule,
    MatIconModule,
  ],
  template: `
    <div class="chat-shell">
      <mat-toolbar color="primary">
        <span>Shapy</span>
        <span class="spacer"></span>
        <span class="user-email">{{ store.currentUserEmail() }}</span>
        <button mat-icon-button (click)="logout()">
          <mat-icon>logout</mat-icon>
        </button>
      </mat-toolbar>

      <div class="chat-content">
        <div class="placeholder">
          <mat-icon class="big-icon">chat</mat-icon>
          <h2>Welcome to Shapy</h2>
          <p>Chat interface will be implemented in Phase 6.3</p>
          <p class="status">
            Connection Status:
            <span [class]="'status-' + store.wsStatus()">
              {{ store.wsStatus() }}
            </span>
          </p>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .chat-shell {
      display: flex;
      flex-direction: column;
      height: 100vh;
    }

    mat-toolbar {
      flex-shrink: 0;
    }

    .spacer {
      flex: 1 1 auto;
    }

    .user-email {
      margin-right: 16px;
      font-size: 14px;
      opacity: 0.9;
    }

    .chat-content {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #f5f5f5;
    }

    .placeholder {
      text-align: center;
      color: #666;
    }

    .big-icon {
      font-size: 64px;
      width: 64px;
      height: 64px;
      color: #ccc;
    }

    .placeholder h2 {
      margin: 16px 0 8px;
      color: #333;
    }

    .placeholder p {
      margin: 4px 0;
    }

    .status {
      margin-top: 16px;
      font-size: 14px;
    }

    .status-disconnected {
      color: #9e9e9e;
    }

    .status-connecting {
      color: #ff9800;
    }

    .status-connected {
      color: #4caf50;
    }

    .status-error {
      color: #f44336;
    }
  `],
})
export class ChatShellComponent implements OnInit {
  readonly store = inject(SessionStore);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);

  ngOnInit(): void {
    this.authService.initializeAuth();
  }

  logout(): void {
    this.authService.logout();
  }
}
