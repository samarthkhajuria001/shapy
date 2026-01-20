import { Component, inject, signal, computed, ViewChild, ElementRef, AfterViewChecked, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatChipsModule } from '@angular/material/chips';

import { SessionStore } from '../../../core/stores/session.store';
import { WebSocketService } from '../../../core/services/websocket.service';

import { MessageBubbleComponent } from './message-bubble.component';
import { ClarificationWidgetComponent } from './clarification-widget.component';
import { ReasoningStepsComponent } from './reasoning-steps.component';
import { StreamingIndicatorComponent } from './streaming-indicator.component';

@Component({
  selector: 'app-chat-panel',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatTooltipModule,
    MatChipsModule,
    MessageBubbleComponent,
    ClarificationWidgetComponent,
    ReasoningStepsComponent,
    StreamingIndicatorComponent,
  ],
  template: `
    <div class="chat-panel">
      <!-- Chat Header -->
      <div class="chat-header">
        <div class="header-info">
          <h3>Chat</h3>
          @if (store.currentSessionId()) {
            <span class="session-id">Session: {{ store.currentSessionId()?.slice(0, 8) }}...</span>
          }
        </div>
        @if (store.hasDrawing()) {
          <mat-chip-set>
            <mat-chip>
              <mat-icon>check_circle</mat-icon>
              Drawing loaded
            </mat-chip>
          </mat-chip-set>
        }
      </div>

      <!-- Message List -->
      <div class="message-list" #messageList>
        @if (store.messages().length === 0 && !store.isAgentThinking()) {
          <div class="empty-chat">
            <mat-icon class="big-icon">question_answer</mat-icon>
            <h3>Ask about UK Permitted Development</h3>
            <p>Get help checking if your extension complies with planning rules</p>
            <div class="suggested-questions">
              @for (question of suggestedQuestions; track question) {
                <button mat-stroked-button (click)="sendMessage(question)">
                  {{ question }}
                </button>
              }
            </div>
          </div>
        } @else {
          @for (message of store.messages(); track message.id) {
            <app-message-bubble [message]="message"></app-message-bubble>
          }

          @if (store.isAgentThinking() && store.reasoningSteps().length > 0) {
            <app-reasoning-steps [steps]="store.reasoningSteps()"></app-reasoning-steps>
          }

          @if (store.isAgentThinking()) {
            <app-streaming-indicator></app-streaming-indicator>
          }

          @if (store.pendingClarification()) {
            <app-clarification-widget
              [clarification]="store.pendingClarification()!"
              (respond)="handleClarificationResponse($event)"
            ></app-clarification-widget>
          }
        }
      </div>

      <!-- Suggested Follow-ups -->
      @if (lastMessageFollowups().length > 0 && !store.isAgentThinking()) {
        <div class="followup-suggestions">
          <span class="followup-label">Suggested:</span>
          @for (followup of lastMessageFollowups(); track followup) {
            <button mat-stroked-button class="followup-btn" (click)="sendMessage(followup)">
              {{ followup }}
            </button>
          }
        </div>
      }

      <!-- Chat Input -->
      <div class="chat-input-container">
        <textarea
          #inputField
          class="chat-input"
          [(ngModel)]="inputText"
          (keydown)="onKeyDown($event)"
          placeholder="Ask about permitted development rules..."
          [disabled]="!canSend()"
          rows="1"
        ></textarea>
        <button
          mat-fab
          color="primary"
          class="send-button"
          [disabled]="!canSend() || !inputText().trim()"
          (click)="send()"
          matTooltip="Send message (Enter)"
        >
          <mat-icon>send</mat-icon>
        </button>
      </div>
    </div>
  `,
  styles: [`
    .chat-panel {
      height: 100%;
      display: flex;
      flex-direction: column;
      background: #fff;
    }

    .chat-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      border-bottom: 1px solid #e0e0e0;
      background: #fafafa;
      flex-shrink: 0;
    }

    .header-info h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 500;
    }

    .session-id {
      font-size: 12px;
      color: #888;
    }

    :host ::ng-deep .chat-header mat-chip {
      font-size: 12px;
    }

    :host ::ng-deep .chat-header mat-chip mat-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      margin-right: 4px;
      color: #4caf50;
    }

    .message-list {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .empty-chat {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      color: #666;
      padding: 24px;
    }

    .empty-chat .big-icon {
      font-size: 64px;
      width: 64px;
      height: 64px;
      color: #ddd;
      margin-bottom: 16px;
    }

    .empty-chat h3 {
      margin: 0 0 8px;
      color: #333;
    }

    .empty-chat p {
      margin: 0 0 24px;
      color: #888;
    }

    .suggested-questions {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-width: 400px;
    }

    .suggested-questions button {
      text-align: left;
      white-space: normal;
      height: auto;
      padding: 12px 16px;
      line-height: 1.4;
    }

    .followup-suggestions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 8px 16px;
      border-top: 1px solid #f0f0f0;
      background: #fafafa;
      align-items: center;
      flex-shrink: 0;
    }

    .followup-label {
      font-size: 12px;
      color: #888;
      margin-right: 4px;
    }

    .followup-btn {
      font-size: 12px;
      height: 32px;
    }

    .chat-input-container {
      display: flex;
      gap: 12px;
      padding: 12px 16px;
      border-top: 1px solid #e0e0e0;
      background: #fafafa;
      align-items: flex-end;
      flex-shrink: 0;
    }

    .chat-input {
      flex: 1;
      padding: 12px 16px;
      font-size: 14px;
      border: 1px solid #e0e0e0;
      border-radius: 24px;
      resize: none;
      outline: none;
      font-family: inherit;
      line-height: 1.5;
      max-height: 120px;
    }

    .chat-input:focus {
      border-color: #673ab7;
      box-shadow: 0 0 0 2px rgba(103, 58, 183, 0.1);
    }

    .chat-input:disabled {
      background: #f5f5f5;
      color: #999;
    }

    .send-button {
      flex-shrink: 0;
    }
  `],
})
export class ChatPanelComponent implements AfterViewChecked {
  readonly store = inject(SessionStore);
  private readonly wsService = inject(WebSocketService);

  @ViewChild('messageList') messageListRef!: ElementRef<HTMLDivElement>;
  @ViewChild('inputField') inputFieldRef!: ElementRef<HTMLTextAreaElement>;

  readonly inputText = signal('');
  private shouldScrollToBottom = false;
  private lastMessageCount = 0;
  private lastStreamingState = false;

  readonly suggestedQuestions = [
    'Can I build a single-storey rear extension?',
    'What is the maximum height for a rear extension?',
    'Do I need planning permission for my extension?',
  ];

  readonly canSend = computed(() => {
    return this.store.wsStatus() === 'connected' &&
           !this.store.isAgentThinking() &&
           !this.store.pendingClarification();
  });

  readonly lastMessageFollowups = computed(() => {
    const messages = this.store.messages();
    if (messages.length === 0) return [];

    const lastMessage = messages[messages.length - 1];
    if (lastMessage.role !== 'assistant') return [];

    return lastMessage.suggestedFollowups || [];
  });

  constructor() {
    // Use effect to scroll when messages or streaming state changes
    effect(() => {
      const messageCount = this.store.messages().length;
      const isThinking = this.store.isAgentThinking();
      const streamingContent = this.store.streamingContent();

      // Trigger scroll on any chat state change
      if (messageCount > 0 || isThinking || streamingContent) {
        this.shouldScrollToBottom = true;
      }
    });
  }

  ngAfterViewChecked(): void {
    const currentCount = this.store.messages().length;
    const currentStreaming = this.store.isAgentThinking();

    // Scroll when message count changes or streaming state changes
    if (currentCount !== this.lastMessageCount || currentStreaming !== this.lastStreamingState) {
      this.lastMessageCount = currentCount;
      this.lastStreamingState = currentStreaming;
      this.shouldScrollToBottom = true;
    }

    if (this.shouldScrollToBottom) {
      this.scrollToBottom();
      this.shouldScrollToBottom = false;
    }
  }

  onKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    }
  }

  send(): void {
    const text = this.inputText().trim();
    if (!text || !this.canSend()) return;

    this.sendMessage(text);
    this.inputText.set('');
    this.shouldScrollToBottom = true;
  }

  sendMessage(text: string): void {
    this.wsService.sendQuery(text);
    this.shouldScrollToBottom = true;
  }

  handleClarificationResponse(response: { questionId: string; value: string; text?: string }): void {
    this.wsService.sendClarificationResponse(response.questionId, response.value, response.text);
    this.shouldScrollToBottom = true;
  }

  private scrollToBottom(): void {
    if (this.messageListRef) {
      const el = this.messageListRef.nativeElement;
      // Use requestAnimationFrame for smoother scrolling after DOM update
      requestAnimationFrame(() => {
        el.scrollTo({
          top: el.scrollHeight,
          behavior: 'smooth'
        });
      });
    }
  }
}
