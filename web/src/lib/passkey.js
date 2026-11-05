// Talks to the device's passkey system. The server sends and expects base64url, and the browser wants raw bytes.
// Options are fetched before the tap, never during it: Safari only allows Face ID straight after a tap, and a
// network request in between can use that permission up.

export function decode(text) {
  const padded = text.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(text.length / 4) * 4, '=');
  return Uint8Array.from(atob(padded), (ch) => ch.charCodeAt(0));
}

export function encode(buffer) {
  let binary = '';
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export const passkeysSupported = () => typeof window !== 'undefined' && 'PublicKeyCredential' in window;

export async function createPasskey(options) {
  const credential = await navigator.credentials.create({
    publicKey: {
      ...options,
      challenge: decode(options.challenge),
      user: { ...options.user, id: decode(options.user.id) },
      excludeCredentials: (options.excludeCredentials ?? []).map((c) => ({ ...c, id: decode(c.id) })),
    },
  });
  return {
    id: credential.id,
    rawId: encode(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      clientDataJSON: encode(credential.response.clientDataJSON),
      attestationObject: encode(credential.response.attestationObject),
    },
  };
}

export async function usePasskey(options) {
  const credential = await navigator.credentials.get({
    publicKey: {
      ...options,
      challenge: decode(options.challenge),
      allowCredentials: (options.allowCredentials ?? []).map((c) => ({ ...c, id: decode(c.id) })),
    },
  });
  return {
    id: credential.id,
    rawId: encode(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      clientDataJSON: encode(credential.response.clientDataJSON),
      authenticatorData: encode(credential.response.authenticatorData),
      signature: encode(credential.response.signature),
      userHandle: credential.response.userHandle ? encode(credential.response.userHandle) : null,
    },
  };
}

/** A sentence to show for a failure. The browser gives cancelling and timing out the same name. */
export function passkeyProblem(failure) {
  switch (failure?.name) {
    case 'NotAllowedError':
      return 'That was cancelled or timed out. Try again.';
    case 'InvalidStateError':
      return 'This device already has a passkey for Creed.';
    case 'SecurityError':
      return "This address can't use passkeys.";
    case 'NotSupportedError':
      return "This device can't create the kind of passkey Creed needs.";
    default:
      return failure?.message || 'Something went wrong. Try again.';
  }
}

export const alreadyHasPasskey = (failure) => failure?.name === 'InvalidStateError';

/** What the user will recognise in the list of passkeys. */
export function deviceName(userAgent = navigator.userAgent) {
  if (/iPhone/.test(userAgent)) return 'iPhone';
  if (/iPad/.test(userAgent)) return 'iPad';
  if (/Android/.test(userAgent)) return 'Android';
  if (/Macintosh/.test(userAgent)) return 'Mac';
  if (/Windows/.test(userAgent)) return 'Windows';
  return 'Passkey';
}

export function unlockName(userAgent = navigator.userAgent) {
  return /iPhone|iPad/.test(userAgent) ? 'Face ID' : 'a passkey';
}
