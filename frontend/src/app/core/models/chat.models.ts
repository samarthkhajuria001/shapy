import {
  CalculationPayload,
  ClarificationRequestPayload,
  SourceCitation,
  Assumption,
} from './websocket.models';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  isStreaming?: boolean;

  // Assistant message metadata
  queryType?: string;
  confidence?: 'high' | 'medium' | 'low';
  sources?: SourceCitation[];
  calculations?: CalculationPayload[];
  assumptions?: Assumption[];
  suggestedFollowups?: string[];
}

export interface ReasoningStep {
  stepIndex: number;
  node: string;
  status: 'processing' | 'completed' | 'skipped';
  message: string;
  timestamp: Date;
}

export interface PendingClarification {
  request: ClarificationRequestPayload;
  receivedAt: Date;
}
