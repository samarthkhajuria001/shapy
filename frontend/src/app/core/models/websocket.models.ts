// Client -> Server message types
export type ClientMessageType = 'query' | 'clarification_response' | 'cancel' | 'ping';

// Server -> Client message types
export type ServerMessageType =
  | 'connected'
  | 'reasoning_step'
  | 'token'
  | 'tokens'
  | 'clarification_request'
  | 'calculation'
  | 'context_updated'
  | 'response_complete'
  | 'error'
  | 'pong';

// Client Messages
export interface ClientMessage {
  type: ClientMessageType;
  payload?: Record<string, unknown>;
}

export interface QueryPayload {
  content: string;
  include_reasoning?: boolean;
}

export interface ClarificationResponsePayload {
  question_id: string;
  value: string;
  text?: string;
}

// Server Messages
export interface ServerMessage {
  type: ServerMessageType;
  payload: Record<string, unknown>;
}

export interface ConnectedPayload {
  session_id: string;
  has_context: boolean;
  context_version: number;
}

export interface ReasoningStepPayload {
  step_index: number;
  node: string;
  status: 'processing' | 'completed' | 'skipped';
  message: string;
  timestamp: string;
}

export interface TokenPayload {
  chunk: string;
  node: string;
  token_index: number;
}

export interface TokensPayload {
  chunks: string[];
  node: string;
}

export interface ClarificationOption {
  label: string;
  value: string;
  description?: string;
}

export interface ClarificationRequestPayload {
  id: string;
  question: string;
  why_needed: string;
  field_name: string;
  options?: ClarificationOption[];
  priority: number;
  affects_rules: string[];
}

export interface VisualizationHint {
  highlight_layers: string[];
  highlight_color: string;
}

export interface CalculationPayload {
  calculation_type: string;
  result: number;
  unit: string;
  limit?: number;
  compliant?: boolean;
  margin?: number;
  description: string;
  visualization_hint?: VisualizationHint;
}

export interface InferredData {
  principal_elevation?: string;
  rear_wall_identified: boolean;
  house_type_detected?: string;
}

export interface ContextUpdatedPayload {
  source: string;
  version: number;
  changes: string[];
  inferred_data?: InferredData;
}

export interface SourceCitation {
  section: string;
  page?: number;
  relevance: number;
}

export interface Assumption {
  field: string;
  value: unknown;
  confidence: 'high' | 'medium' | 'low';
}

export interface ResponseCompletePayload {
  message_id: string;
  final_answer: string;
  confidence: 'high' | 'medium' | 'low';
  query_type: string;
  sources: SourceCitation[];
  calculations: CalculationPayload[];
  assumptions: Assumption[];
  suggested_followups: string[];
}

export interface ErrorPayload {
  code: string;
  message: string;
  recoverable: boolean;
}
