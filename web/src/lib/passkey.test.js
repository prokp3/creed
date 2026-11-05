import { afterEach, describe, expect, it, vi } from 'vitest';
import { alreadyHasPasskey, createPasskey, decode, deviceName, encode, passkeyProblem, unlockName, usePasskey } from './passkey.js';

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15';
const WINDOWS = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0';

const bytes = (...values) => new Uint8Array(values).buffer;

afterEach(() => vi.unstubAllGlobals());

describe('base64url', () => {
  it('matches a worked example, including the two characters that differ from plain base64', () => {
    expect(encode(bytes(0xfb, 0xff, 0xfe))).toBe('-__-');
    expect([...decode('-__-')]).toEqual([0xfb, 0xff, 0xfe]);
  });

  it.each([[[1], 'AQ'], [[1, 2], 'AQI'], [[1, 2, 3], 'AQID'], [[], '']])('handles every padding length: %j', (values, text) => {
    expect(encode(bytes(...values))).toBe(text);
    expect([...decode(text)]).toEqual(values);
  });
});

describe('createPasskey', () => {
  it('turns the server options into bytes and the answer back into text', async () => {
    const create = vi.fn(async () => ({
      id: 'abc',
      rawId: bytes(1, 2, 3),
      type: 'public-key',
      getClientExtensionResults: () => ({}),
      response: { clientDataJSON: bytes(4), attestationObject: bytes(5) },
    }));
    vi.stubGlobal('navigator', { credentials: { create } });

    const answer = await createPasskey({
      challenge: 'AQID',
      user: { id: 'AQI', name: 'Creed' },
      excludeCredentials: [{ id: 'AQ', type: 'public-key' }],
      rp: { id: 'localhost' },
    });

    const sent = create.mock.calls[0][0].publicKey;
    expect([...sent.challenge]).toEqual([1, 2, 3]);
    expect([...sent.user.id]).toEqual([1, 2]);
    expect(sent.user.name).toBe('Creed');
    expect([...sent.excludeCredentials[0].id]).toEqual([1]);
    expect(sent.rp).toEqual({ id: 'localhost' });
    expect(answer).toEqual({
      id: 'abc',
      rawId: 'AQID',
      type: 'public-key',
      clientExtensionResults: {},
      response: { clientDataJSON: 'BA', attestationObject: 'BQ' },
    });
  });
});

describe('usePasskey', () => {
  const answerWith = (userHandle) => ({
    id: 'abc',
    rawId: bytes(1),
    type: 'public-key',
    getClientExtensionResults: () => ({}),
    response: { clientDataJSON: bytes(2), authenticatorData: bytes(3), signature: bytes(4), userHandle },
  });

  it('sends the challenge as bytes and returns every part as text', async () => {
    const get = vi.fn(async () => answerWith(bytes(5)));
    vi.stubGlobal('navigator', { credentials: { get } });

    const answer = await usePasskey({ challenge: 'AQID', allowCredentials: [], userVerification: 'required' });

    const sent = get.mock.calls[0][0].publicKey;
    expect([...sent.challenge]).toEqual([1, 2, 3]);
    expect(sent.userVerification).toBe('required');
    expect(answer.response).toEqual({ clientDataJSON: 'Ag', authenticatorData: 'Aw', signature: 'BA', userHandle: 'BQ' });
  });

  it('copes with no user handle', async () => {
    vi.stubGlobal('navigator', { credentials: { get: async () => answerWith(null) } });
    expect((await usePasskey({ challenge: 'AQ' })).response.userHandle).toBeNull();
  });
});

describe('passkeyProblem', () => {
  it('explains the failures a person can actually hit', () => {
    expect(passkeyProblem({ name: 'NotAllowedError' })).toContain('cancelled');
    expect(passkeyProblem({ name: 'InvalidStateError' })).toContain('already has');
    expect(passkeyProblem({ name: 'SecurityError' })).toContain('address');
  });

  it('passes a server message through and never shows nothing', () => {
    expect(passkeyProblem(new Error('That passkey was refused.'))).toBe('That passkey was refused.');
    expect(passkeyProblem(undefined)).toBeTruthy();
  });

  it('recognises a device that already has one', () => {
    expect(alreadyHasPasskey({ name: 'InvalidStateError' })).toBe(true);
    expect(alreadyHasPasskey({ name: 'NotAllowedError' })).toBe(false);
  });
});

describe('device wording', () => {
  it('names the device and how it unlocks', () => {
    expect(deviceName(IPHONE)).toBe('iPhone');
    expect(unlockName(IPHONE)).toBe('Face ID');
    expect(deviceName(WINDOWS)).toBe('Windows');
    expect(unlockName(WINDOWS)).toBe('a passkey');
    expect(deviceName('something else')).toBe('Passkey');
  });
});
