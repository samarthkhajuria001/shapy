import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-streaming-indicator',
  standalone: true,
  imports: [CommonModule, MatIconModule],
  template: `
    <div class="streaming-indicator">
      <div class="avatar">
        <mat-icon>smart_toy</mat-icon>
      </div>
      <div class="typing-dots">
        <span class="dot"></span>
        <span class="dot"></span>
        <span class="dot"></span>
      </div>
    </div>
  `,
  styles: [`
    .streaming-indicator {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .avatar {
      width: 36px;
      height: 36px;
      background: #f0f0f0;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .avatar mat-icon {
      color: #673ab7;
    }

    .typing-dots {
      display: flex;
      gap: 4px;
      padding: 12px 16px;
      background: #f5f5f5;
      border-radius: 4px 18px 18px 18px;
    }

    .dot {
      width: 8px;
      height: 8px;
      background: #888;
      border-radius: 50%;
      animation: bounce 1.4s infinite ease-in-out both;
    }

    .dot:nth-child(1) {
      animation-delay: -0.32s;
    }

    .dot:nth-child(2) {
      animation-delay: -0.16s;
    }

    @keyframes bounce {
      0%, 80%, 100% {
        transform: scale(0.8);
        opacity: 0.5;
      }
      40% {
        transform: scale(1);
        opacity: 1;
      }
    }
  `],
})
export class StreamingIndicatorComponent {}
