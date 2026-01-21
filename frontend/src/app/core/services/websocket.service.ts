import { Injectable, inject, OnDestroy } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subject, Observable, timer, EMPTY } from 'rxjs';
import { webSocket, WebSocketSubject } from 'rxjs/webSocket';
import { retry, catchError, takeUntil } from 'rxjs/operators';
import { environment } from '../../../environments/environment';
import { SessionStore } from '../stores/session.store';
import {
  ServerMessage,
  ClientMessage,
  QueryPayload,
  ClarificationResponsePayload,
  ConnectedPayload,
  ReasoningStepPayload,
  TokenPayload,
  TokensPayload,
  ClarificationRequestPayload,
  CalculationPayload,
  ContextUpdatedPayload,
  ResponseCompletePayload,
  ErrorPayload,
  MessagesResponse,
} from '../models';

@Injectable({ providedIn: 'root' })
export class WebSocketService implements OnDestroy {
  private readonly store = inject(SessionStore);
  private readonly http = inject(HttpClient);
  private socket$: WebSocketSubject<ServerMessage> | null = null;
  private readonly destroy$ = new Subject<void>();
  private readonly messages$ = new Subject<ServerMessage>();
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 5;
  private pingInterval: ReturnType<typeof setInterval> | null = null;
  private currentSessionId: string | null = null;
  private currentMessageId: string | null = null;

  readonly onMessage$: Observable<ServerMessage> = this.messages$.asObservable();

  connect(sessionId: string, token: string): void {
    if (this.socket$) {
      this.disconnect();
    }

    this.currentSessionId = sessionId;
    this.store.setConnectionStatus('connecting');

    const wsUrl = this.buildWsUrl(sessionId, token);

    this.socket$ = webSocket<ServerMessage>({
      url: wsUrl,
      openObserver: {
        next: () => {
          this.reconnectAttempts = 0;
          this.startPingInterval();
        },
      },
      closeObserver: {
        next: (event) => {
          this.stopPingInterval();
          if (event.wasClean) {
            this.store.setConnectionStatus('disconnected');
          } else {
            this.handleDisconnect();
          }
        },
      },
    });

    this.socket$
      .pipe(
        takeUntil(this.destroy$),
        catchError((error) => {
          this.store.setConnectionStatus('error', error.message);
          return EMPTY;
        })
      )
      .subscribe({
        next: (message) => this.handleMessage(message),
        error: (error) => {
          this.store.setConnectionStatus('error', error.message);
          this.handleDisconnect();
        },
      });
  }

  disconnect(): void {
    this.stopPingInterval();
    if (this.socket$) {
      this.socket$.complete();
      this.socket$ = null;
    }
    this.currentSessionId = null;
    this.store.setConnectionStatus('disconnected');
  }

  sendQuery(content: string, includeReasoning = true): void {
    if (!this.socket$ || this.store.wsStatus() !== 'connected') {
      return;
    }

    this.currentMessageId = this.store.addUserMessage(content);
    this.store.startAssistantMessage();

    const payload: QueryPayload = {
      content,
      include_reasoning: includeReasoning,
    };

    const message: ClientMessage = {
      type: 'query',
      payload: payload as unknown as Record<string, unknown>,
    };

    this.socket$.next(message as unknown as ServerMessage);
  }

  sendClarificationResponse(questionId: string, value: string, text?: string): void {
    if (!this.socket$ || this.store.wsStatus() !== 'connected') {
      return;
    }

    this.store.setPendingClarification(null);
    this.store.startAssistantMessage();

    const payload: ClarificationResponsePayload = {
      question_id: questionId,
      value,
      text,
    };

    const message: ClientMessage = {
      type: 'clarification_response',
      payload: payload as unknown as Record<string, unknown>,
    };

    this.socket$.next(message as unknown as ServerMessage);
  }

  sendCancel(): void {
    if (!this.socket$) {
      return;
    }

    const message: ClientMessage = {
      type: 'cancel',
    };

    this.socket$.next(message as unknown as ServerMessage);
  }

  private buildWsUrl(sessionId: string, token: string): string {
    let baseUrl = environment.wsUrl;

    if (!baseUrl && environment.production) {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      baseUrl = `${protocol}//${window.location.host}/ws`;
    }

    return `${baseUrl}/chat/${sessionId}?token=${encodeURIComponent(token)}`;
  }

  private handleMessage(message: ServerMessage): void {
    this.messages$.next(message);

    switch (message.type) {
      case 'connected':
        this.handleConnected(message.payload as unknown as ConnectedPayload);
        break;

      case 'reasoning_step':
        this.handleReasoningStep(message.payload as unknown as ReasoningStepPayload);
        break;

      case 'token':
        this.handleToken(message.payload as unknown as TokenPayload);
        break;

      case 'tokens':
        this.handleTokens(message.payload as unknown as TokensPayload);
        break;

      case 'clarification_request':
        this.handleClarificationRequest(message.payload as unknown as ClarificationRequestPayload);
        break;

      case 'calculation':
        this.handleCalculation(message.payload as unknown as CalculationPayload);
        break;

      case 'context_updated':
        this.handleContextUpdated(message.payload as unknown as ContextUpdatedPayload);
        break;

      case 'response_complete':
        this.handleResponseComplete(message.payload as unknown as ResponseCompletePayload);
        break;

      case 'error':
        this.handleError(message.payload as unknown as ErrorPayload);
        break;

      case 'pong':
        break;
    }
  }

  private handleConnected(payload: ConnectedPayload): void {
    this.store.setConnectionStatus('connected');
    this.store.updateContextVersion(payload.context_version);

    // Load message history from backend
    if (this.currentSessionId) {
      this.http
        .get<MessagesResponse>(
          `${environment.apiUrl}/session/${this.currentSessionId}/messages`
        )
        .subscribe({
          next: (response) => {
            if (response.messages && response.messages.length > 0) {
              this.store.loadMessages(response.messages);
            }
          },
          error: (error) => {
            console.warn('Failed to load message history:', error);
          },
        });
    }
  }

  private handleReasoningStep(payload: ReasoningStepPayload): void {
    this.store.addReasoningStep({
      stepIndex: payload.step_index,
      node: payload.node,
      status: payload.status,
      message: payload.message,
      timestamp: new Date(payload.timestamp),
    });
  }

  private handleToken(payload: TokenPayload): void {
    this.store.appendToStreamingContent(payload.chunk);
  }

  private handleTokens(payload: TokensPayload): void {
    const combined = payload.chunks.join('');
    this.store.appendToStreamingContent(combined);
  }

  private handleClarificationRequest(payload: ClarificationRequestPayload): void {
    this.store.setPendingClarification(payload);
  }

  private handleCalculation(_payload: CalculationPayload): void {
    // Calculations are included in response_complete
    // This event is for real-time UI updates if needed
  }

  private handleContextUpdated(payload: ContextUpdatedPayload): void {
    this.store.updateContextVersion(payload.version);
  }

  private handleResponseComplete(payload: ResponseCompletePayload): void {
    const messages = this.store.messages();
    const lastMessage = messages[messages.length - 1];

    if (lastMessage && lastMessage.role === 'assistant') {
      this.store.finalizeAssistantMessage(lastMessage.id, payload.final_answer, {
        queryType: payload.query_type,
        confidence: payload.confidence,
        sources: payload.sources,
        calculations: payload.calculations,
        assumptions: payload.assumptions,
        suggestedFollowups: payload.suggested_followups,
      });
    }
  }

  private handleError(payload: ErrorPayload): void {
    this.store.setConnectionStatus('error', payload.message);

    if (!payload.recoverable) {
      this.disconnect();
    }
  }

  private handleDisconnect(): void {
    if (this.reconnectAttempts < this.maxReconnectAttempts && this.currentSessionId) {
      this.reconnectAttempts++;
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);

      timer(delay)
        .pipe(takeUntil(this.destroy$))
        .subscribe(() => {
          const token = localStorage.getItem('access_token');
          if (token && this.currentSessionId) {
            this.connect(this.currentSessionId, token);
          }
        });
    } else {
      this.store.setConnectionStatus('error', 'Connection failed after multiple attempts');
    }
  }

  private startPingInterval(): void {
    this.stopPingInterval();
    this.pingInterval = setInterval(() => {
      if (this.socket$) {
        const message: ClientMessage = { type: 'ping' };
        this.socket$.next(message as unknown as ServerMessage);
      }
    }, 30000);
  }

  private stopPingInterval(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.disconnect();
  }
}
