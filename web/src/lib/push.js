// Notifications on this phone. On iPhone they only work in the app added to the home screen (iOS 16.4 or later),
// and iOS asks permission once, after a tap. The phone's push address goes to Creed's server and nowhere else.
import { post } from './api.js';

export function pushSupport() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    const standalone = window.matchMedia?.('(display-mode: standalone)').matches || navigator.standalone;
    return standalone ? 'unsupported' : 'needs-home-screen';
  }
  return 'supported';
}

export const permission = () => ('Notification' in window ? Notification.permission : 'default');

function keyBytes(base64url) {
  const padded = base64url.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (base64url.length % 4)) % 4);
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

const sameKey = (subscription, publicKey) => {
  const current = subscription.options?.applicationServerKey;
  if (!current) return true;
  const a = new Uint8Array(current);
  const b = keyBytes(publicKey);
  return a.length === b.length && a.every((v, i) => v === b[i]);
};

async function registration() {
  const ready = navigator.serviceWorker.ready;
  const timeout = new Promise((_, reject) =>
    setTimeout(() => reject(new Error('Notifications need the installed app. Open Creed from your home screen.')), 4000),
  );
  return Promise.race([ready, timeout]);
}

/** Ask permission (after a tap), subscribe, and tell the server. Throws a message to show if it can't. */
export async function startNotifications(publicKey) {
  if (!publicKey) throw new Error("Notifications aren't set up on the server yet.");
  if (pushSupport() !== 'supported') throw new Error('Notifications need Creed added to your home screen (iOS 16.4 or later).');
  const answer = await Notification.requestPermission();
  if (answer !== 'granted') throw new Error('Notifications are off for Creed. Turn them on in Settings › Notifications › Creed.');
  const reg = await registration();
  let subscription = await reg.pushManager.getSubscription();
  if (subscription && !sameKey(subscription, publicKey)) {
    await subscription.unsubscribe();
    subscription = null;
  }
  subscription ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) });
  await post('/api/push/subscribe', subscription.toJSON());
}

/** Stop notifications to this phone. Quiet if there were none. */
export async function stopNotifications() {
  try {
    if (pushSupport() !== 'supported') return;
    const reg = await navigator.serviceWorker.getRegistration();
    const subscription = await reg?.pushManager.getSubscription();
    if (!subscription) return;
    await post('/api/push/unsubscribe', { endpoint: subscription.endpoint }).catch(() => {});
    await subscription.unsubscribe();
  } catch {
    // Nothing to undo.
  }
}

/** Whether this phone is subscribed right now. */
export async function isSubscribed() {
  try {
    if (pushSupport() !== 'supported') return false;
    const reg = await navigator.serviceWorker.getRegistration();
    return Boolean(await reg?.pushManager.getSubscription());
  } catch {
    return false;
  }
}

export const sendTest = () => post('/api/push/test');
