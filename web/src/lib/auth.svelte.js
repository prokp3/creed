import { get, onSessionEnded } from './api.js';

// Which of the app's three faces to show: the sign-in screens, the app, or "can't reach the server".
let status = $state('loading');
let hasPasskey = $state(false);
let sessionKind = $state(null);
let problem = $state(null);

export async function checkAuth() {
  try {
    const result = await get('/api/auth/status');
    hasPasskey = result.has_passkey;
    sessionKind = result.session_kind;
    problem = null;
    status = result.signed_in ? 'signed-in' : 'signed-out';
  } catch (failure) {
    problem = failure.message;
    status = 'unreachable';
  }
}

onSessionEnded(checkAuth);

export const auth = {
  get status() {
    return status;
  },
  get hasPasskey() {
    return hasPasskey;
  },
  get sessionKind() {
    return sessionKind;
  },
  get problem() {
    return problem;
  },
};
