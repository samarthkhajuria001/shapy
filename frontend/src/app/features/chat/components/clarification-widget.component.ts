import { Component, Input, Output, EventEmitter, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatRadioModule } from '@angular/material/radio';

import { PendingClarification } from '../../../core/models';

@Component({
  selector: 'app-clarification-widget',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatTooltipModule,
    MatRadioModule,
  ],
  template: `
    <mat-card class="clarification-card">
      <mat-card-header>
        <mat-icon mat-card-avatar class="clarify-icon">help_outline</mat-icon>
        <mat-card-title>Clarification Needed</mat-card-title>
        <mat-card-subtitle>{{ clarification.request.question }}</mat-card-subtitle>
      </mat-card-header>

      <mat-card-content>
        <!-- Why Needed -->
        <div class="why-needed">
          <mat-icon>info</mat-icon>
          <span>{{ clarification.request.why_needed }}</span>
        </div>

        <!-- Options -->
        @if (clarification.request.options && clarification.request.options.length > 0) {
          <div class="options-group">
            <mat-radio-group [(ngModel)]="selectedOption" class="options-list">
              @for (option of clarification.request.options; track option.value) {
                <mat-radio-button [value]="option.value" class="option-item">
                  <div class="option-content">
                    <span class="option-label">{{ option.label }}</span>
                    @if (option.description) {
                      <span class="option-description">{{ option.description }}</span>
                    }
                  </div>
                </mat-radio-button>
              }
            </mat-radio-group>
          </div>
        }

        <!-- Custom Input -->
        <div class="custom-input">
          <mat-form-field appearance="outline" class="full-width">
            <mat-label>
              {{ clarification.request.options ? 'Or type your answer' : 'Your answer' }}
            </mat-label>
            <input
              matInput
              [(ngModel)]="customText"
              (keydown.enter)="submit()"
              placeholder="Type here..."
            />
          </mat-form-field>
        </div>

        <!-- Affects Rules -->
        @if (clarification.request.affects_rules.length > 0) {
          <div class="affects-rules">
            <span class="affects-label">This affects:</span>
            @for (rule of clarification.request.affects_rules; track rule) {
              <span class="rule-chip">{{ rule }}</span>
            }
          </div>
        }
      </mat-card-content>

      <mat-card-actions align="end">
        <button
          mat-raised-button
          color="primary"
          [disabled]="!canSubmit()"
          (click)="submit()"
        >
          <mat-icon>send</mat-icon>
          Submit Answer
        </button>
      </mat-card-actions>
    </mat-card>
  `,
  styles: [`
    .clarification-card {
      margin: 8px 0;
      border-left: 4px solid #ff9800;
      animation: slideIn 0.3s ease-out;
    }

    @keyframes slideIn {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .clarify-icon {
      background: #fff3e0;
      color: #ff9800;
      width: 40px;
      height: 40px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
    }

    .why-needed {
      display: flex;
      gap: 8px;
      padding: 12px;
      background: #f5f5f5;
      border-radius: 8px;
      margin-bottom: 16px;
      font-size: 14px;
      color: #666;
    }

    .why-needed mat-icon {
      font-size: 20px;
      width: 20px;
      height: 20px;
      color: #888;
      flex-shrink: 0;
    }

    .options-group {
      margin-bottom: 16px;
    }

    .options-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .option-item {
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      padding: 12px 16px;
      transition: border-color 0.2s, background 0.2s;
    }

    .option-item:hover {
      border-color: #673ab7;
      background: rgba(103, 58, 183, 0.04);
    }

    ::ng-deep .option-item.mat-mdc-radio-checked {
      border-color: #673ab7;
      background: rgba(103, 58, 183, 0.08);
    }

    .option-content {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .option-label {
      font-weight: 500;
    }

    .option-description {
      font-size: 12px;
      color: #888;
    }

    .custom-input {
      margin-bottom: 8px;
    }

    .full-width {
      width: 100%;
    }

    .affects-rules {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding: 8px 0;
    }

    .affects-label {
      font-size: 12px;
      color: #888;
    }

    .rule-chip {
      font-size: 11px;
      padding: 4px 8px;
      background: #e3f2fd;
      color: #1976d2;
      border-radius: 4px;
    }

    mat-card-actions button mat-icon {
      margin-right: 4px;
    }
  `],
})
export class ClarificationWidgetComponent {
  @Input() clarification!: PendingClarification;
  @Output() respond = new EventEmitter<{ questionId: string; value: string; text?: string }>();

  selectedOption = '';
  customText = '';

  canSubmit(): boolean {
    return !!(this.selectedOption || this.customText.trim());
  }

  submit(): void {
    if (!this.canSubmit()) return;

    const value = this.selectedOption || this.customText.trim();
    const text = this.customText.trim() || undefined;

    this.respond.emit({
      questionId: this.clarification.request.id,
      value,
      text,
    });
  }
}
