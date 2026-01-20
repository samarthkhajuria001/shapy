export interface BoundingBox {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
}

export interface ContextMetadata {
  uploaded_at: string;
  object_count: number;
  coordinate_unit: string;
  context_version: number;
  layers_present: string[];
  layer_counts: Record<string, number>;
  has_plot_boundary: boolean;
  plot_boundary_closed: boolean;
  bounding_box?: BoundingBox;
}

export interface SessionCreateResponse {
  session_id: string;
  created_at: string;
}

export interface SessionStatusResponse {
  session_id: string;
  user_id: string;
  created_at: string;
  updated_at?: string;
  expires_at: string;
  has_context: boolean;
  context_metadata?: ContextMetadata;
}

export interface ContextUpdateRequest {
  objects: DrawingObject[];
}

export interface ContextUpdateResponse {
  object_count: number;
  layers: string[];
  layer_counts: Record<string, number>;
  warnings: string[];
  updated_at: string;
}

export interface ContextGetResponse {
  objects: DrawingObject[];
  metadata: ContextMetadata;
}

export interface SessionListItem {
  session_id: string;
  created_at: string;
  updated_at?: string;
  has_context: boolean;
  object_count: number;
}

export interface SessionListResponse {
  sessions: SessionListItem[];
  count: number;
}

// Drawing object types
export interface LineObject {
  type: 'LINE';
  layer: string;
  start: [number, number];
  end: [number, number];
}

export interface PolylineObject {
  type: 'POLYLINE';
  layer: string;
  points: [number, number][];
  closed?: boolean;
}

export type DrawingObject = LineObject | PolylineObject;
