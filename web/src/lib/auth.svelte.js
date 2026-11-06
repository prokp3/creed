import { get, onSessionEnded } from './api.js';

// Which of the app's three faces to show: the sign-in screens, the app, or "can't reach the server".
let status = $state('loading');
let hasPasskey = $state(false);
let sessionKind = $state(null);
let problem = $state(null);

// Whether this phone was signed in last time, so the app can open with no signal and log food offline. Only a
// yes or no is kept; the session itself stays in its HttpOnly cookie, and the server still checks it every time.
const REMEMBER = 'creed-signed-in';

function remembered() {
  try {
    return localStorage.getItem(REMEMBER) === '1';
  } catch {
    return false;
  }
}

function remember(signedIn) {
  try {
    if (signedIn) localStorage.setItem(REMEMBER, '1');
    else localStorage.removeItem(REMEMBER);
  } catch {
    // Private browsing: the app just won't open offline.
  }
}

export async function checkAuth() {
  try {
    const result = await get('/api/auth/status');
    hasPasskey = result.has_passkey;
    sessionKind = result.session_kind;
    problem = null;
    status = result.signed_in ? 'signed-in' : 'signed-out';
    remember(result.signed_in);
  } catch (failure) {
    problem = failure.message;
    // No signal at all: open as before if this phone was signed in. Anything else is a real problem to show.
    status = failure.status === 0 && remembered() ? 'signed-in' : 'unreachable';
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
