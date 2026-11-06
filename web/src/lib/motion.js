import { tick } from 'svelte';

const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** How long a small reveal should last, which is no time at all for someone who has asked for less motion. */
export const revealMs = () => (reduced() ? 0 : 200);

/** Where a screen sits, so going deeper slides in from the right and coming back slides the other way. */
const DEPTH = { today: 0, 'in-depth': 0, activities: 0, food: 0, settings: 1, activity: 1, 'activity-map': 2 };

/** Which movement a change of screen deserves, or null if the screen isn't changing. */
export function motionBetween(from, to) {
  if (from === to) return null;
  const difference = (DEPTH[to] ?? 0) - (DEPTH[from] ?? 0);
  if (difference > 0) return 'push';
  if (difference < 0) return 'pop';
  return 'tab';
}

/** Run a change of screen with a page animation where the browser has them, and without one where it doesn't. */
export function changeScreen(kind, update) {
  if (!kind || !document.startViewTransition || reduced()) {
    update();
    return;
  }
  const root = document.documentElement;
  root.dataset.motion = kind;
  const transition = document.startViewTransition(async () => {
    update();
    await tick();
  });
  // A skipped animation, such as one started while the app is in the background, still changes the screen.
  transition.ready.catch(() => {});
  transition.finished.catch(() => {}).finally(() => {
    if (root.dataset.motion === kind) delete root.dataset.motion;
  });
}
