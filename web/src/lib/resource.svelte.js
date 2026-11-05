import { get } from './api.js';

/**
 * Data for one screen. While it refreshes, the previous data stays on screen with no flash of emptiness.
 * If the screen moves on, such as to a new date range, a slower older response is ignored.
 */
export function resource(getPath) {
  let data = $state(null);
  let error = $state(null);
  let loading = $state(false);
  let latest = 0;

  async function load() {
    const ticket = ++latest;
    loading = true;
    try {
      const result = await get(getPath());
      if (ticket === latest) {
        data = result;
        error = null;
      }
    } catch (failure) {
      if (ticket === latest) error = failure;
    } finally {
      if (ticket === latest) loading = false;
    }
  }

  return {
    get data() {
      return data;
    },
    get error() {
      return error;
    },
    get loading() {
      return loading;
    },
    load,
  };
}
