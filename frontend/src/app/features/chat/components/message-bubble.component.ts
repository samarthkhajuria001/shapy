import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ChatMessage, CalculationPayload, SourceCitation } from '../../../core/models';

@Component({
  selector: 'app-message-bubble',
  standalone: true,
  imports: [
    CommonModule,
    MatIconModule,
    MatExpansionModule,
    MatChipsModule,
    MatTooltipModule,
  ],
  template: `
    <div class="message-bubble" [class.user]="message.role === 'user'" [class.assistant]="message.role === 'assistant'">
      <!-- User Message -->
      @if (message.role === 'user') {
        <div class="message-content user-message">
          {{ message.content }}
        </div>
        <div class="message-time">
          {{ formatTime(message.timestamp) }}
        </div>
      }

      <!-- Assistant Message -->
      @if (message.role === 'assistant') {
        <div class="assistant-wrapper">
          <div class="avatar">
            <mat-icon>smart_toy</mat-icon>
          </div>
          <div class="message-body">
            <div class="message-content assistant-message" [innerHTML]="formatMarkdown(message.content)">
            </div>

            <!-- Calculations -->
            @if (message.calculations && message.calculations.length > 0) {
              <div class="calculations-section">
                <h4>Calculations</h4>
                <div class="calculations-grid">
                  @for (calc of message.calculations; track calc.calculation_type) {
                    <div class="calculation-card" [class.compliant]="calc.compliant === true" [class.non-compliant]="calc.compliant === false">
                      <div class="calc-header">
                        <mat-icon>{{ calc.compliant === true ? 'check_circle' : calc.compliant === false ? 'cancel' : 'calculate' }}</mat-icon>
                        <span>{{ formatCalcType(calc.calculation_type) }}</span>
                      </div>
                      <div class="calc-value">
                        {{ calc.result | number:'1.0-2' }} {{ calc.unit }}
                      </div>
                      @if (calc.limit !== null && calc.limit !== undefined) {
                        <div class="calc-limit">
                          Limit: {{ calc.limit }} {{ calc.unit }}
                        </div>
                      }
                      @if (calc.margin !== null && calc.margin !== undefined) {
                        <div class="calc-margin" [class.positive]="calc.margin >= 0" [class.negative]="calc.margin < 0">
                          {{ calc.margin >= 0 ? '+' : '' }}{{ calc.margin | number:'1.0-2' }} {{ calc.unit }} margin
                        </div>
                      }
                    </div>
                  }
                </div>
              </div>
            }

            <!-- Sources -->
            @if (message.sources && message.sources.length > 0) {
              <mat-expansion-panel class="sources-panel">
                <mat-expansion-panel-header>
                  <mat-panel-title>
                    <mat-icon>menu_book</mat-icon>
                    Sources ({{ message.sources.length }})
                  </mat-panel-title>
                </mat-expansion-panel-header>
                <div class="sources-list">
                  @for (source of message.sources; track source.section) {
                    <div class="source-item">
                      <span class="source-section">{{ source.section }}</span>
                      @if (source.page) {
                        <span class="source-page">Page {{ source.page }}</span>
                      }
                    </div>
                  }
                </div>
              </mat-expansion-panel>
            }

            <!-- Confidence & Metadata -->
            <div class="message-meta">
              @if (message.confidence) {
                <mat-chip [class]="'confidence-' + message.confidence" matTooltip="Confidence level">
                  {{ message.confidence }}
                </mat-chip>
              }
              @if (message.queryType) {
                <mat-chip matTooltip="Query type">
                  {{ formatQueryType(message.queryType) }}
                </mat-chip>
              }
              <span class="message-time">{{ formatTime(message.timestamp) }}</span>
            </div>
          </div>
        </div>
      }
    </div>
  `,
  styles: [`
    .message-bubble {
      display: flex;
      flex-direction: column;
    }

    .message-bubble.user {
      align-items: flex-end;
    }

    .message-bubble.assistant {
      align-items: flex-start;
    }

    .user-message {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 12px 16px;
      border-radius: 18px 18px 4px 18px;
      max-width: 70%;
      word-wrap: break-word;
    }

    .assistant-wrapper {
      display: flex;
      gap: 12px;
      max-width: 85%;
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

    .message-body {
      flex: 1;
      min-width: 0;
    }

    .assistant-message {
      background: #f5f5f5;
      padding: 12px 16px;
      border-radius: 4px 18px 18px 18px;
      line-height: 1.6;
    }

    .assistant-message ::ng-deep p {
      margin: 0 0 12px;
    }

    .assistant-message ::ng-deep p:last-child {
      margin-bottom: 0;
    }

    .assistant-message ::ng-deep h2.md-header,
    .assistant-message ::ng-deep h3.md-header,
    .assistant-message ::ng-deep h4.md-header {
      margin: 16px 0 8px;
      font-weight: 600;
      color: #333;
    }

    .assistant-message ::ng-deep h2.md-header:first-child,
    .assistant-message ::ng-deep h3.md-header:first-child,
    .assistant-message ::ng-deep h4.md-header:first-child {
      margin-top: 0;
    }

    .assistant-message ::ng-deep h2.md-header {
      font-size: 18px;
    }

    .assistant-message ::ng-deep h3.md-header {
      font-size: 16px;
    }

    .assistant-message ::ng-deep h4.md-header {
      font-size: 14px;
      color: #555;
    }

    .assistant-message ::ng-deep hr.md-divider {
      border: none;
      border-top: 1px solid #ddd;
      margin: 16px 0;
    }

    .assistant-message ::ng-deep .md-list-item {
      margin: 4px 0;
      padding-left: 8px;
    }

    .assistant-message ::ng-deep ul,
    .assistant-message ::ng-deep ol {
      margin: 8px 0;
      padding-left: 24px;
    }

    .assistant-message ::ng-deep code {
      background: #e8e8e8;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 13px;
    }

    .assistant-message ::ng-deep strong {
      font-weight: 600;
    }

    .calculations-section {
      margin-top: 12px;
    }

    .calculations-section h4 {
      margin: 0 0 8px;
      font-size: 13px;
      color: #666;
      font-weight: 500;
    }

    .calculations-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 8px;
    }

    .calculation-card {
      background: #fff;
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      padding: 12px;
    }

    .calculation-card.compliant {
      border-color: #4caf50;
      background: #f1f8e9;
    }

    .calculation-card.non-compliant {
      border-color: #f44336;
      background: #ffebee;
    }

    .calc-header {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: #666;
      margin-bottom: 4px;
    }

    .calc-header mat-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
    }

    .compliant .calc-header mat-icon {
      color: #4caf50;
    }

    .non-compliant .calc-header mat-icon {
      color: #f44336;
    }

    .calc-value {
      font-size: 20px;
      font-weight: 600;
      color: #333;
    }

    .calc-limit {
      font-size: 12px;
      color: #888;
      margin-top: 4px;
    }

    .calc-margin {
      font-size: 12px;
      margin-top: 4px;
    }

    .calc-margin.positive {
      color: #4caf50;
    }

    .calc-margin.negative {
      color: #f44336;
    }

    .sources-panel {
      margin-top: 12px;
      box-shadow: none !important;
      border: 1px solid #e0e0e0;
    }

    ::ng-deep .sources-panel .mat-expansion-panel-header {
      padding: 0 12px;
      height: 40px;
    }

    ::ng-deep .sources-panel mat-panel-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
    }

    ::ng-deep .sources-panel mat-panel-title mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
    }

    .sources-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .source-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px;
      background: #fafafa;
      border-radius: 4px;
    }

    .source-section {
      font-size: 13px;
      color: #333;
    }

    .source-page {
      font-size: 12px;
      color: #888;
    }

    .message-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 8px;
      flex-wrap: wrap;
    }

    .message-meta mat-chip {
      font-size: 11px;
      height: 24px;
    }

    .confidence-high {
      background: #e8f5e9 !important;
      color: #2e7d32 !important;
    }

    .confidence-medium {
      background: #fff3e0 !important;
      color: #f57c00 !important;
    }

    .confidence-low {
      background: #ffebee !important;
      color: #c62828 !important;
    }

    .message-time {
      font-size: 11px;
      color: #999;
      margin-top: 4px;
    }

    .user .message-time {
      text-align: right;
    }
  `],
})
export class MessageBubbleComponent {
  @Input() message!: ChatMessage;

  formatTime(date: Date): string {
    return date.toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  formatMarkdown(content: string): string {
    if (!content) return '';

    // Process inline formatting first
    let html = content
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code>$1</code>');

    const lines = html.split('\n');
    let inList = false;
    let result: string[] = [];

    for (const line of lines) {
      const trimmed = line.trim();

      // Handle headers (### Header)
      if (trimmed.startsWith('### ')) {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        result.push(`<h4 class="md-header">${trimmed.substring(4)}</h4>`);
      } else if (trimmed.startsWith('## ')) {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        result.push(`<h3 class="md-header">${trimmed.substring(3)}</h3>`);
      } else if (trimmed.startsWith('# ')) {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        result.push(`<h2 class="md-header">${trimmed.substring(2)}</h2>`);
      }
      // Handle unordered lists
      else if (trimmed.startsWith('- ')) {
        if (!inList) {
          result.push('<ul>');
          inList = true;
        }
        result.push(`<li>${trimmed.substring(2)}</li>`);
      }
      // Handle numbered lists
      else if (/^\d+\.\s/.test(trimmed)) {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        const listContent = trimmed.replace(/^\d+\.\s/, '');
        result.push(`<p class="md-list-item">• ${listContent}</p>`);
      }
      // Handle horizontal rules
      else if (trimmed === '---' || trimmed === '***') {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        result.push('<hr class="md-divider">');
      }
      // Regular paragraphs
      else {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        if (trimmed) {
          result.push(`<p>${line}</p>`);
        }
      }
    }

    if (inList) {
      result.push('</ul>');
    }

    return result.join('');
  }

  formatCalcType(type: string): string {
    return type
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  }

  formatQueryType(type: string): string {
    return type
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  }
}
