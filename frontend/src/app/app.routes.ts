import { Routes } from '@angular/router';
import { authGuard, noAuthGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'chat',
    pathMatch: 'full',
  },
  {
    path: 'login',
    loadComponent: () =>
      import('./features/auth/login.component').then((m) => m.LoginComponent),
    canActivate: [noAuthGuard],
  },
  {
    path: 'register',
    loadComponent: () =>
      import('./features/auth/register.component').then((m) => m.RegisterComponent),
    canActivate: [noAuthGuard],
  },
  {
    path: 'chat',
    loadComponent: () =>
      import('./features/chat/chat-shell.component').then((m) => m.ChatShellComponent),
    canActivate: [authGuard],
  },
  {
    path: '**',
    redirectTo: 'chat',
  },
];
