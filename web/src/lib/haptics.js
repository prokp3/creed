// A small tap you can feel on links and buttons. Android has a vibration feature. iPhone has none for web apps, so
// ios-haptics uses the one thing that does buzz there: an invisible label over the element, wired to a hidden
// switch. It's a workaround rather than a promise from Apple, so a future iOS could quietly stop it.
import { hapticTrigger } from 'ios-haptics';

const TARGETS = 'a[href^="#"], button';
// Forms and passkey buttons stay as they are: getting in matters more than a buzz, and the invisible label could
// get in the way of a submit button. Map controls have their own touch handling and outside links.
const LEFT_ALONE = 'form, [data-no-haptics], .maplibregl-map';
const VIBRATE_MS = 8;

function attach(root) {
  if (root.nodeType !== Node.ELEMENT_NODE) return;
  const elements = root.matches(TARGETS) ? [root] : [];
  elements.push(...root.querySelectorAll(TARGETS));
  for (const element of elements) {
    if (!element.closest(LEFT_ALONE)) hapticTrigger(element);
  }
}

/** A tap lands on the invisible label, and Safari may not then follow the link it sits in, so this makes sure. */
function followLink(event) {
  const trigger = event.target.closest?.('[data-haptic-trigger]');
  const link = trigger?.parentElement;
  if (link?.matches('a[href^="#"]')) location.hash = link.getAttribute('href');
}

function vibrate(event) {
  if (event.target.closest?.(TARGETS) && !event.target.closest(LEFT_ALONE)) navigator.vibrate?.(VIBRATE_MS);
}

export function installHaptics(root = document.body) {
  attach(root);
  new MutationObserver((changes) => {
    for (const change of changes) change.addedNodes.forEach(attach);
  }).observe(root, { childList: true, subtree: true });
  document.addEventListener('click', followLink);
  document.addEventListener('click', vibrate);
}
