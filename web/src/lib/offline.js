// A small key-value store in this phone's IndexedDB, so food logging works with no signal. It holds your food
// library, recent days and changes not yet sent. It's cleared when you sign out. Every call fails quietly
// (private browsing, storage full, blocked): the app then works as before, online only.
const NAME = 'creed-food';
const STORE = 'kv';

let opening = null;

function open() {
  if (!opening) {
    opening = new Promise((resolve) => {
      try {
        const request = indexedDB.open(NAME, 1);
        request.onupgradeneeded = () => request.result.createObjectStore(STORE);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => resolve(null);
        request.onblocked = () => resolve(null);
      } catch {
        resolve(null);
      }
    });
  }
  return opening;
}

async function run(mode, action) {
  const db = await open();
  if (!db) return undefined;
  return new Promise((resolve) => {
    try {
      const transaction = db.transaction(STORE, mode);
      const request = action(transaction.objectStore(STORE));
      transaction.oncomplete = () => resolve(request?.result);
      transaction.onerror = () => resolve(undefined);
      transaction.onabort = () => resolve(undefined);
    } catch {
      resolve(undefined);
    }
  });
}

export const read = (key) => run('readonly', (store) => store.get(key));
export const write = (key, value) => run('readwrite', (store) => store.put(value, key));
export const remove = (key) => run('readwrite', (store) => store.delete(key));
export const keys = async () => (await run('readonly', (store) => store.getAllKeys())) ?? [];
export const clearAll = () => run('readwrite', (store) => store.clear());
