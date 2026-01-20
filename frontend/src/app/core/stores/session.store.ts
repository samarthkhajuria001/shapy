import { Injectable, computed, signal } from '@angular/core';
import {
  ChatMessage,
  ReasoningStep,
  PendingClarification,
  SessionListItem,
  DrawingObject,
  ContextMetadata,
  ClarificationRequestPayload,
} from '../models';

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

@Injectable({ providedIn: 'root' })
export class SessionStore {
  // Session state
  readonly currentSessionId = signal<string | null>(null);
  readonly sessions = signal<SessionListItem[]>([]);

  // Connection state
  readonly wsStatus = signal<ConnectionStatus>('disconnected');
  readonly wsError = signal<string | null>(null);

  // Drawing context state
  readonly drawingObjects = signal<DrawingObject[]>([]);
  readonly contextMetadata = signal<ContextMetadata | null>(null);
  readonly contextVersion = signal<number>(0);

  // Chat state
  readonly messages = signal<ChatMessage[]>([]);
  readonly reasoningSteps = signal<ReasoningStep[]>([]);
  readonly isAgentThinking = signal<boolean>(false);
  readonly streamingContent = signal<string>('');
  readonly pendingClarification = signal<PendingClarification | null>(null);

  // Auth state
  readonly isAuthenticated = signal<boolean>(false);
  readonly currentUserId = signal<string | null>(null);
  readonly currentUserEmail = signal<string | null>(null);

  // Derived state
  readonly hasDrawing = computed(() => this.drawingObjects().length > 0);
  readonly hasPlotBoundary = computed(() => this.contextMetadata()?.has_plot_boundary ?? false);
  readonly isWaitingForUser = computed(() => this.pendingClarification() !== null);
  readonly canSendQuery = computed(
    () =>
      this.wsStatus() === 'connected' &&
      !this.isAgentThinking() &&
      !this.isWaitingForUser()
  );
  readonly layersPresent = computed(() => this.contextMetadata()?.layers_present ?? []);

  // Session actions
  setCurrentSession(sessionId: string | null): void {
    this.currentSessionId.set(sessionId);
    if (sessionId === null) {
      this.clearChatState();
      this.clearDrawingState();
    }
  }

  setSessions(sessions: SessionListItem[]): void {
    this.sessions.set(sessions);
  }

  addSession(session: SessionListItem): void {
    this.sessions.update((current) => [session, ...current]);
  }

  removeSession(sessionId: string): void {
    this.sessions.update((current) => current.filter((s) => s.session_id !== sessionId));
    if (this.currentSessionId() === sessionId) {
      this.setCurrentSession(null);
    }
  }

  // Connection actions
  setConnectionStatus(status: ConnectionStatus, error?: string): void {
    this.wsStatus.set(status);
    this.wsError.set(error ?? null);
  }

  // Drawing context actions
  setDrawingContext(objects: DrawingObject[], metadata: ContextMetadata): void {
    this.drawingObjects.set(objects);
    this.contextMetadata.set(metadata);
    this.contextVersion.set(metadata.context_version);
  }

  updateContextVersion(version: number): void {
    this.contextVersion.set(version);
  }

  clearDrawingState(): void {
    this.drawingObjects.set([]);
    this.contextMetadata.set(null);
    this.contextVersion.set(0);
  }

  // Chat actions
  addUserMessage(content: string): string {
    const id = crypto.randomUUID();
    const message: ChatMessage = {
      id,
      role: 'user',
      content,
      timestamp: new Date(),
    };
    this.messages.update((current) => [...current, message]);
    return id;
  }

  startAssistantMessage(): string {
    const id = crypto.randomUUID();
    const message: ChatMessage = {
      id,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
    };
    this.messages.update((current) => [...current, message]);
    this.isAgentThinking.set(true);
    this.streamingContent.set('');
    this.reasoningSteps.set([]);
    return id;
  }

  appendToStreamingContent(chunk: string): void {
    this.streamingContent.update((current) => current + chunk);
  }

  finalizeAssistantMessage(
    messageId: string,
    finalContent: string,
    metadata: {
      queryType?: string;
      confidence?: 'high' | 'medium' | 'low';
      sources?: ChatMessage['sources'];
      calculations?: ChatMessage['calculations'];
      assumptions?: ChatMessage['assumptions'];
      suggestedFollowups?: string[];
    }
  ): void {
    this.messages.update((current) =>
      current.map((msg) =>
        msg.id === messageId
          ? {
              ...msg,
              content: finalContent,
              isStreaming: false,
              ...metadata,
            }
          : msg
      )
    );
    this.isAgentThinking.set(false);
    this.streamingContent.set('');
  }

  addReasoningStep(step: ReasoningStep): void {
    this.reasoningSteps.update((current) => {
      const existing = current.findIndex((s) => s.stepIndex === step.stepIndex);
      if (existing >= 0) {
        const updated = [...current];
        updated[existing] = step;
        return updated;
      }
      return [...current, step];
    });
  }

  setPendingClarification(request: ClarificationRequestPayload | null): void {
    if (request) {
      this.pendingClarification.set({
        request,
        receivedAt: new Date(),
      });
      this.isAgentThinking.set(false);
    } else {
      this.pendingClarification.set(null);
    }
  }

  clearChatState(): void {
    this.messages.set([]);
    this.reasoningSteps.set([]);
    this.isAgentThinking.set(false);
    this.streamingContent.set('');
    this.pendingClarification.set(null);
  }

  // Auth actions
  setAuthenticated(userId: string, email: string): void {
    this.isAuthenticated.set(true);
    this.currentUserId.set(userId);
    this.currentUserEmail.set(email);
  }

  clearAuth(): void {
    this.isAuthenticated.set(false);
    this.currentUserId.set(null);
    this.currentUserEmail.set(null);
    this.setCurrentSession(null);
    this.setSessions([]);
  }
}
