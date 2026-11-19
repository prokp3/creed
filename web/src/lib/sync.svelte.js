import { post } from './api.js';

// One sync state for the whole app, so the Today button spins whether you tapped it or the app started one itself.
let syncing = $state(false);
let problem = $state(null);
let finished = $state(0);

const FAILED = ['failed', 'auth_failed'];

/**
 * Sync now pulls from the source whatever happens. Opening the app asks the server to sync, and it skips the
 * source when a sync is running or finished a few minutes ago. A startup sync stays quiet if it can't run;
 * a failed one still shows on the Today button, which reads the latest run.
 */
async function run(path, quiet) {
  if (syncing) return;
  syncing = true;
  problem = null;
  try {
    const result = await post(path);
    if (FAILED.includes(result.status)) problem = "The sync didn't work. Try again later.";
  } catch (failure) {
    if (!quiet) problem = failure.message;
  } finally {
    syncing = false;
    finished += 1;
  }
}

export const syncNow = () => run('/api/sync', false);
export const syncOnOpen = () => run('/api/sync/open', true);

export const sync = {
  get syncing() {
    return syncing;
  },
  get problem() {
    return problem;
  },
  /** Goes up each time a sync ends, so screens know to reload. */
  get finished() {
    return finished;
  },
};
