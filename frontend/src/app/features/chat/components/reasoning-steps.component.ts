import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { ReasoningStep } from '../../../core/models';

@Component({
  selector: 'app-reasoning-steps',
  standalone: true,
  imports: [
    CommonModule,
    MatExpansionModule,
    MatIconModule,
    MatProgressSpinnerModule,
  ],
  template: `
    <mat-expansion-panel class="reasoning-panel" [expanded]="true">
      <mat-expansion-panel-header>
        <mat-panel-title>
          <mat-icon>psychology</mat-icon>
          <span>Reasoning</span>
        </mat-panel-title>
        <mat-panel-description>
          {{ completedSteps }} / {{ steps.length }} steps
        </mat-panel-description>
      </mat-expansion-panel-header>

      <div class="steps-list">
        @for (step of steps; track step.stepIndex) {
          <div class="step-item" [class]="'status-' + step.status">
            <div class="step-indicator">
              @if (step.status === 'processing') {
                <mat-spinner diameter="16"></mat-spinner>
              } @else if (step.status === 'completed') {
                <mat-icon>check_circle</mat-icon>
              } @else {
                <mat-icon>remove_circle_outline</mat-icon>
              }
            </div>
            <div class="step-content">
              <span class="step-node">{{ formatNodeName(step.node) }}</span>
              <span class="step-message">{{ step.message }}</span>
            </div>
          </div>
        }
      </div>
    </mat-expansion-panel>
  `,
  styles: [`
    .reasoning-panel {
      margin: 8px 0;
      box-shadow: none !important;
      border: 1px solid #e0e0e0;
      background: #fafafa;
    }

    ::ng-deep .reasoning-panel .mat-expansion-panel-header {
      height: 44px;
      padding: 0 16px;
    }

    ::ng-deep .reasoning-panel mat-panel-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      font-weight: 500;
    }

    ::ng-deep .reasoning-panel mat-panel-title mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
      color: #673ab7;
    }

    ::ng-deep .reasoning-panel mat-panel-description {
      font-size: 12px;
    }

    .steps-list {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .step-item {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      padding: 8px 0;
      border-bottom: 1px solid #f0f0f0;
    }

    .step-item:last-child {
      border-bottom: none;
    }

    .step-indicator {
      width: 20px;
      height: 20px;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .step-indicator mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
    }

    .status-completed .step-indicator mat-icon {
      color: #4caf50;
    }

    .status-processing .step-indicator {
      color: #673ab7;
    }

    .status-skipped .step-indicator mat-icon {
      color: #9e9e9e;
    }

    .step-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .step-node {
      font-size: 12px;
      font-weight: 500;
      color: #333;
    }

    .step-message {
      font-size: 12px;
      color: #666;
    }

    .status-skipped .step-node,
    .status-skipped .step-message {
      color: #999;
    }
  `],
})
export class ReasoningStepsComponent {
  @Input() steps: ReasoningStep[] = [];

  get completedSteps(): number {
    return this.steps.filter(s => s.status === 'completed').length;
  }

  formatNodeName(node: string): string {
    return node
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  }
}
