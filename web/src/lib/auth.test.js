import { beforeEach, describe, expect, it, vi } from 'vitest';

// A tiny stand-in for the browser's storage and network.
function setUp(storage, fetchImpl) {
  vi.resetModules();
  globalThis.localStorage = {
    getItem: (k) => (k in storage ? storage[k] : null),
    setItem: (k, v) => (storage[k] = String(v)),
    removeItem: (k) => delete storage[k],
  };
  globalThis.fetch = vi.fn(fetchImpl);
}

const ok = (body) => async () => ({ ok: true, status: 200, json: async () => body });
const offline = async () => {
  throw new TypeError('Failed to fetch');
};

describe('opening the app', () => {
  let storage;
  beforeEach(() => {
    storage = {};
  });

  it('remembers a signed-in phone, and forgets on sign-out', async () => {
    setUp(storage, ok({ signed_in: true, has_passkey: true, session_kind: 'passkey' }));
    const { auth, checkAuth } = await import('./auth.svelte.js');
    await checkAuth();
    expect(auth.status).toBe('signed-in');
    expect(storage['creed-signed-in']).toBe('1');
    globalThis.fetch = vi.fn(ok({ signed_in: false, has_passkey: true, session_kind: null }));
    await checkAuth();
    expect(auth.status).toBe('signed-out');
    expect(storage['creed-signed-in']).toBeUndefined();
  });

  it('opens with no signal if this phone was signed in, so food can be logged offline', async () => {
    setUp({ 'creed-signed-in': '1' }, offline);
    const { auth, checkAuth } = await import('./auth.svelte.js');
    await checkAuth();
    expect(auth.status).toBe('signed-in');
  });

  it("says it can't reach Creed when it never was signed in, or the server answers with an error", async () => {
    setUp({}, offline);
    let mod = await import('./auth.svelte.js');
    await mod.checkAuth();
    expect(mod.auth.status).toBe('unreachable');
    setUp({ 'creed-signed-in': '1' }, async () => ({ ok: false, status: 503, json: async () => ({ detail: 'Set CREED_ORIGIN' }) }));
    mod = await import('./auth.svelte.js');
    await mod.checkAuth();
    expect(mod.auth.status).toBe('unreachable');
  });
});
