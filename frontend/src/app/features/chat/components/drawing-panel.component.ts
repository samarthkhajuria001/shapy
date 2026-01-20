import { Component, inject, signal, computed, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatTabsModule } from '@angular/material/tabs';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { SessionStore } from '../../../core/stores/session.store';
import { SessionService } from '../../../core/services/session.service';
import { DrawingObject } from '../../../core/models';

@Component({
  selector: 'app-drawing-panel',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatTabsModule,
    MatButtonModule,
    MatIconModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
  ],
  template: `
    <div class="drawing-panel">
      <mat-tab-group animationDuration="200ms">
        <!-- Visual Tab -->
        <mat-tab>
          <ng-template mat-tab-label>
            <mat-icon>visibility</mat-icon>
            <span>Visual</span>
          </ng-template>
          <div class="tab-content">
            @if (store.hasDrawing()) {
              <div class="drawing-preview">
                <svg
                  class="drawing-svg"
                  [attr.viewBox]="viewBox()"
                  preserveAspectRatio="xMidYMid meet"
                >
                  <g [attr.transform]="svgTransform()">
                    @for (obj of store.drawingObjects(); track $index) {
                      @if (obj.type === 'LINE') {
                        <line
                          [attr.x1]="obj.start[0]"
                          [attr.y1]="obj.start[1]"
                          [attr.x2]="obj.end[0]"
                          [attr.y2]="obj.end[1]"
                          [attr.stroke]="getLayerColor(obj.layer)"
                          stroke-width="100"
                          stroke-linecap="round"
                        />
                      } @else if (obj.type === 'POLYLINE') {
                        <polyline
                          [attr.points]="getPolylinePoints(obj)"
                          [attr.stroke]="getLayerColor(obj.layer)"
                          [attr.fill]="obj.closed ? 'rgba(100,100,100,0.1)' : 'none'"
                          stroke-width="100"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        />
                      }
                    }
                  </g>
                </svg>
              </div>
              <div class="drawing-info">
                <span class="info-item">
                  <mat-icon>layers</mat-icon>
                  {{ store.layersPresent().length }} layers
                </span>
                <span class="info-item">
                  <mat-icon>category</mat-icon>
                  {{ store.drawingObjects().length }} objects
                </span>
              </div>
            } @else {
              <div class="no-drawing">
                <mat-icon class="big-icon">architecture</mat-icon>
                <p>No drawing loaded</p>
                <p class="hint">Paste JSON in the JSON tab to visualize</p>
              </div>
            }
          </div>
        </mat-tab>

        <!-- JSON Tab -->
        <mat-tab>
          <ng-template mat-tab-label>
            <mat-icon>code</mat-icon>
            <span>JSON</span>
          </ng-template>
          <div class="tab-content json-tab">
            <textarea
              class="json-editor"
              [ngModel]="jsonContent()"
              (ngModelChange)="onJsonChange($event)"
              placeholder="Paste your drawing JSON here or upload a file..."
              spellcheck="false"
            ></textarea>

            @if (jsonError()) {
              <div class="json-error">
                <mat-icon>error</mat-icon>
                <span>{{ jsonError() }}</span>
              </div>
            }

            <div class="json-actions">
              <input
                type="file"
                #fileInput
                accept=".json"
                (change)="onFileSelected($event)"
                hidden
              />
              <button
                mat-stroked-button
                (click)="fileInput.click()"
                class="action-btn"
              >
                <mat-icon>upload_file</mat-icon>
                <span>Upload JSON</span>
              </button>

              <button
                mat-raised-button
                color="primary"
                [disabled]="!canSave()"
                (click)="saveJson()"
                class="action-btn"
              >
                @if (isSaving()) {
                  <mat-spinner diameter="20"></mat-spinner>
                } @else if (justSaved()) {
                  <ng-container>
                    <mat-icon>check</mat-icon>
                    <span>Saved!</span>
                  </ng-container>
                } @else {
                  <ng-container>
                    <mat-icon>save</mat-icon>
                    <span>Save Context</span>
                  </ng-container>
                }
              </button>
            </div>

            @if (lastSavedTime()) {
              <div class="save-timestamp">
                <mat-icon>schedule</mat-icon>
                <span>Last saved: {{ formatBerlinTime(lastSavedTime()!) }}</span>
              </div>
            }
          </div>
        </mat-tab>
      </mat-tab-group>
    </div>
  `,
  styles: [`
    .drawing-panel {
      height: 100%;
      display: flex;
      flex-direction: column;
    }

    :host ::ng-deep .mat-mdc-tab-group {
      height: 100%;
      display: flex;
      flex-direction: column;
    }

    :host ::ng-deep .mat-mdc-tab-body-wrapper {
      flex: 1;
      min-height: 0;
    }

    :host ::ng-deep .mat-mdc-tab-body {
      height: 100%;
      overflow: hidden;
    }

    :host ::ng-deep .mat-mdc-tab-body-content {
      height: 100%;
      overflow: hidden;
    }

    :host ::ng-deep .mat-mdc-tab-label-container {
      background: #fafafa;
      border-bottom: 1px solid #e0e0e0;
    }

    :host ::ng-deep .mdc-tab__text-label {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .tab-content {
      height: 100%;
      padding: 16px;
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
    }

    /* Visual Tab */
    .drawing-preview {
      flex: 1;
      background: #f9f9f9;
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      overflow: hidden;
    }

    .drawing-svg {
      width: 100%;
      height: 100%;
      background: white;
    }

    .drawing-info {
      display: flex;
      gap: 16px;
      padding-top: 12px;
      justify-content: center;
      flex-shrink: 0;
    }

    .info-item {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 13px;
      color: #666;
    }

    .info-item mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
    }

    .no-drawing {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      color: #999;
    }

    .no-drawing .big-icon {
      font-size: 64px;
      width: 64px;
      height: 64px;
      color: #ddd;
    }

    .no-drawing p {
      margin: 8px 0 0;
    }

    .no-drawing .hint {
      font-size: 13px;
      color: #bbb;
    }

    /* JSON Tab */
    .json-tab {
      gap: 12px;
    }

    .json-editor {
      flex: 1;
      width: 100%;
      padding: 12px;
      font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
      font-size: 13px;
      line-height: 1.5;
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      resize: none;
      background: #fafafa;
      color: #333;
      outline: none;
      box-sizing: border-box;
    }

    .json-editor:focus {
      border-color: #673ab7;
      box-shadow: 0 0 0 2px rgba(103, 58, 183, 0.1);
    }

    .json-editor::placeholder {
      color: #aaa;
    }

    .json-error {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      background: #ffebee;
      color: #c62828;
      border-radius: 4px;
      font-size: 13px;
      flex-shrink: 0;
    }

    .json-error mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
    }

    .json-actions {
      display: flex;
      gap: 12px;
      flex-shrink: 0;
    }

    .action-btn {
      flex: 1;
      height: 44px;
    }

    .action-btn mat-spinner {
      display: inline-block;
    }

    .save-timestamp {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      font-size: 12px;
      color: #888;
      flex-shrink: 0;
    }

    .save-timestamp mat-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
    }
  `],
})
export class DrawingPanelComponent {
  readonly store = inject(SessionStore);
  private readonly sessionService = inject(SessionService);

  readonly jsonContent = signal('');
  readonly jsonError = signal<string | null>(null);
  readonly isSaving = signal(false);
  readonly justSaved = signal(false);
  readonly lastSavedTime = signal<Date | null>(null);

  readonly canSave = computed(() => {
    const content = this.jsonContent().trim();
    return content.length > 0 && !this.jsonError() && !this.isSaving();
  });

  readonly viewBox = computed(() => {
    const metadata = this.store.contextMetadata();
    if (!metadata?.bounding_box) {
      return '0 0 10000 10000';
    }
    const bb = metadata.bounding_box;
    const padding = 1000;
    const minX = bb.min_x - padding;
    const minY = bb.min_y - padding;
    const width = bb.max_x - bb.min_x + padding * 2;
    const height = bb.max_y - bb.min_y + padding * 2;
    return `${minX} ${minY} ${width} ${height}`;
  });

  readonly svgTransform = computed(() => {
    const metadata = this.store.contextMetadata();
    if (!metadata?.bounding_box) {
      return 'scale(1, -1) translate(0, -10000)';
    }
    const bb = metadata.bounding_box;
    const translateY = -(bb.min_y + bb.max_y);
    return `scale(1, -1) translate(0, ${translateY})`;
  });

  private layerColors: Record<string, string> = {
    'Plot Boundary': '#4caf50',
    'Existing House': '#2196f3',
    'Proposed Extension': '#ff9800',
    'Neighbours': '#9e9e9e',
    'Default': '#333333',
  };

  constructor() {
    effect(() => {
      const objects = this.store.drawingObjects();
      if (objects.length > 0) {
        this.jsonContent.set(JSON.stringify(objects, null, 2));
      }
    });
  }

  onJsonChange(value: string): void {
    this.jsonContent.set(value);
    this.justSaved.set(false);

    if (!value.trim()) {
      this.jsonError.set(null);
      return;
    }

    try {
      const parsed = JSON.parse(value);
      if (!Array.isArray(parsed)) {
        this.jsonError.set('JSON must be an array of drawing objects');
        return;
      }
      this.jsonError.set(null);
    } catch (e) {
      this.jsonError.set('Invalid JSON syntax');
    }
  }

  saveJson(): void {
    const sessionId = this.store.currentSessionId();
    if (!sessionId || !this.canSave()) {
      return;
    }

    let objects: DrawingObject[];
    try {
      objects = JSON.parse(this.jsonContent());
    } catch {
      return;
    }

    this.isSaving.set(true);

    this.sessionService.updateContext(sessionId, objects).subscribe({
      next: () => {
        this.isSaving.set(false);
        this.justSaved.set(true);
        this.lastSavedTime.set(new Date());

        this.sessionService.getContext(sessionId).subscribe({
          next: (ctx) => {
            this.store.setDrawingContext(ctx.objects, ctx.metadata);
          },
        });

        setTimeout(() => this.justSaved.set(false), 2000);
      },
      error: (error) => {
        this.isSaving.set(false);
        const message = error.error?.detail || 'Failed to save context';
        this.jsonError.set(message);
      },
    });
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files || input.files.length === 0) {
      return;
    }

    const file = input.files[0];
    const reader = new FileReader();

    reader.onload = () => {
      const content = reader.result as string;
      this.jsonContent.set(content);
      this.onJsonChange(content);
    };

    reader.onerror = () => {
      this.jsonError.set('Failed to read file');
    };

    reader.readAsText(file);
    input.value = '';
  }

  formatBerlinTime(date: Date): string {
    return date.toLocaleString('en-GB', {
      timeZone: 'Europe/Berlin',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      day: '2-digit',
      month: 'short',
    }) + ' CET';
  }

  getLayerColor(layer: string): string {
    return this.layerColors[layer] || this.layerColors['Default'];
  }

  getPolylinePoints(obj: DrawingObject): string {
    if (obj.type !== 'POLYLINE') return '';
    return obj.points.map(p => `${p[0]},${p[1]}`).join(' ');
  }
}
