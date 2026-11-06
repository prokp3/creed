// The food logger's shared state: the library, each loaded day, and changes on their way to the server.
//
// A tap changes the screen at once and joins a queue saved on the phone. The queue goes to the server one change at
// a time, in order, so an undo never overtakes the log it undoes. With no signal, changes wait and go when the phone
// is back online, even after the app is closed. Until the server has a change and the screen has read the data
// back, the change is laid over the last data the server sent, so nothing flickers away.
//
// The library and recent days are kept on the phone too, so the Food tab opens without a signal. All of it is
// cleared when you sign out.
import { ApiError, get, post } from './api.js';
import * as F from './food.js';
import * as store from './offline.js';

const KEEP_DAYS = 31;
const RETRY_MS = 15000;

let library = $state(null);
let libraryError = $state(null);
let days = $state({});
let pending = $state([]);
let toast = $state(null);
let online = $state(true);

let counter = 0;
let loadTicket = 0;
let libraryTicket = 0;
const latestLoad = {};
let toastTimer = null;
let flushing = false;
let retryTimer = null;
let started = false;

const now = () => new Date().toISOString();
const isEntryChange = (change) => ['save', 'delete', 'delete-groups', 'day-type'].includes(change.kind);

// ---------------------------------------------------------------- saved on the phone

function savePending() {
  const items = $state.snapshot(pending).map(({ id, change, requests, dates, account, confirmedAt }) => ({
    id,
    change,
    requests,
    dates,
    account,
    confirmed: confirmedAt !== null,
  }));
  store.write('pending', items);
}

/** Read what this phone kept, then send anything still waiting. Called once after signing in. */
export async function startFood() {
  if (started) return;
  started = true;
  const [savedLibrary, savedPending, savedKeys] = await Promise.all([
    store.read('library'),
    store.read('pending'),
    store.keys(),
  ]);
  if (savedLibrary && !library) library = savedLibrary;
  if (Array.isArray(savedPending) && savedPending.length) {
    pending = [
      ...savedPending.map((item) => ({
        ...item,
        id: ++counter,
        confirmedAt: item.confirmed ? -1 : null,
        waiting: new Set(item.confirmed ? item.dates : []),
      })),
      ...pending,
    ];
  }
  const dayKeys = savedKeys.filter((k) => typeof k === 'string' && k.startsWith('day:')).sort();
  for (const key of dayKeys.slice(0, -KEEP_DAYS)) store.remove(key);
  for (const key of dayKeys.slice(-KEEP_DAYS)) {
    const date = key.slice(4);
    if (!days[date]) {
      const data = await store.read(key);
      if (data && !days[date]) days[date] = { data, error: null };
    }
  }
  window.addEventListener('online', flush);
  flush();
}

/** Forget everything kept on this phone. Called when signing out. */
export async function clearFood() {
  library = null;
  days = {};
  pending = [];
  toast = null;
  await store.clearAll();
}

// ---------------------------------------------------------------- reading

export async function loadLibrary() {
  const ticket = ++libraryTicket;
  try {
    const fresh = await get('/api/food/library');
    if (ticket !== libraryTicket) return;
    if (library?.account && fresh.account !== library.account) {
      // Someone else signed in on this phone: nothing of the last person's stays.
      days = {};
      pending = pending.filter((p) => p.account === fresh.account);
      await store.clearAll();
    }
    library = fresh;
    libraryError = null;
    online = true;
    store.write('library', fresh);
    dropConfirmedLibrary(ticket);
  } catch (failure) {
    if (ticket === libraryTicket) {
      libraryError = failure;
      if (failure.status === 0) online = false;
    }
  }
}

/** A confirmed library change stops being laid over once a library read that started after it has arrived. */
function dropConfirmedLibrary(ticket) {
  const before = pending.length;
  pending = pending.filter((item) => isEntryChange(item.change) || item.confirmedAt === null || item.confirmedAt >= ticket);
  if (pending.length !== before) savePending();
}

export async function loadDay(date) {
  const ticket = ++loadTicket;
  latestLoad[date] = ticket;
  if (!days[date]) days[date] = { data: null, error: null };
  try {
    const data = await get(`/api/food/day?date=${date}`);
    if (latestLoad[date] !== ticket) return;
    days[date] = { data, error: null };
    online = true;
    store.write(`day:${date}`, data);
    // A confirmed change can stop being laid over once each day it touched has been read back since.
    const before = pending.length;
    pending = pending.filter((item) => {
      if (!isEntryChange(item.change)) return true;
      if (item.confirmedAt !== null && item.confirmedAt < ticket) item.waiting.delete(date);
      return item.confirmedAt === null || item.waiting.size > 0;
    });
    if (pending.length !== before) savePending();
  } catch (failure) {
    if (latestLoad[date] === ticket) {
      days[date] = { data: days[date]?.data ?? null, error: failure };
      if (failure.status === 0) online = false;
    }
  }
}

/** The library as the screen shows it, with changes still on their way laid over it. */
export function libraryView() {
  return F.applyLibraryChanges(
    library,
    pending.filter((item) => !isEntryChange(item.change)).map((item) => item.change),
  );
}

function emptyDay(date) {
  return {
    date,
    is_today: date === F.localDate(),
    day_type: { type: 'rest', how: 'unknown', threshold_minutes: library?.settings?.training_minutes ?? 20 },
    targets_from: null,
    nutrients: library?.nutrients ?? [],
    totals: {},
    incomplete: [],
    rings: [],
    meals: [],
    balance: { tag: 'Garmin', estimate: true, so_far: date === F.localDate(), eaten_kcal: 0, burned_kcal: null, net_kcal: null },
  };
}

/** One day as the screen shows it: the server's entries with changes still on their way laid over them. */
export function dayView(date) {
  const state = days[date];
  let data = state?.data;
  // With no signal and nothing kept for this day, it starts empty so food can still be logged.
  const guessed = !data && state?.error?.status === 0 && library !== null;
  if (guessed) data = emptyDay(date);
  if (!data) return { date, loaded: false, error: state?.error ?? null };
  const lib = libraryView();
  const changes = pending.map((item) => item.change);
  const server = data.meals.flatMap((meal) => meal.entries);
  const entries = F.applyChanges(server, changes).filter((e) => e.local_date === date);
  const nutrients = lib?.nutrients ?? data.nutrients;
  const sums = F.totals(
    entries,
    nutrients.map((n) => n.id),
  );
  let dayType = { ...data.day_type };
  const chosen = changes.filter((c) => c.kind === 'day-type' && c.date === date).at(-1);
  if (chosen?.value) dayType = { ...dayType, type: chosen.value, how: 'override' };
  const targetSet = lib
    ? F.targetsFor(date, dayType.type, lib.targets)
    : data.rings.length
      ? { effective_from: data.targets_from, targets: Object.fromEntries(data.rings.map((r) => [r.id, r.target])) }
      : null;
  const eaten = sums.values.kcal ?? 0;
  const burned = data.balance.burned_kcal;
  return {
    date,
    loaded: true,
    guessed,
    error: state.error,
    isToday: date === F.localDate(),
    dayType,
    entries,
    meals: F.meals(entries),
    totals: sums,
    progress: F.progress(nutrients, sums, targetSet),
    targetSet,
    balance: { ...data.balance, eaten_kcal: eaten, net_kcal: burned === null ? null : eaten - burned },
  };
}

// ---------------------------------------------------------------- the toast

function showToast(text, { undo = null, problem = false } = {}) {
  clearTimeout(toastTimer);
  toast = { id: ++counter, text, undo, problem };
  toastTimer = setTimeout(() => (toast = null), undo ? 6000 : 4000);
}

export function dismissToast() {
  clearTimeout(toastTimer);
  toast = null;
}

export function undoToast() {
  const shown = toast;
  dismissToast();
  shown?.undo?.();
}

/** A message for things done outside the store, such as an import. */
export function say(text, problem = false) {
  showToast(text, { problem });
}

// ---------------------------------------------------------------- the queue

function scheduleRetry() {
  clearTimeout(retryTimer);
  retryTimer = setTimeout(flush, RETRY_MS);
}

/** Send waiting changes in order. Stops at the first one that can't reach the server, and tries again later. */
export async function flush() {
  if (flushing) return;
  flushing = true;
  try {
    for (;;) {
      const item = pending.find((p) => p.confirmedAt === null);
      if (!item) break;
      if (library?.account && item.account && item.account !== library.account) {
        pending = pending.filter((p) => p.id !== item.id);
        savePending();
        continue;
      }
      let results;
      try {
        ({ results } = await post('/api/food/changes', { changes: item.requests }));
      } catch (failure) {
        if (failure instanceof ApiError && (failure.status === 0 || failure.status === 401 || failure.status >= 500)) {
          // No signal, signed out, or the server is having a moment: keep it and try again.
          if (failure.status === 0) online = false;
          scheduleRetry();
          break;
        }
        pending = pending.filter((p) => p.id !== item.id);
        savePending();
        showToast(`Not saved. ${failure.message}`, { problem: true });
        continue;
      }
      online = true;
      const refused = results.find((r) => 'error' in r);
      if (refused) {
        pending = pending.filter((p) => p.id !== item.id);
        savePending();
        showToast(`Not saved. ${refused.error}`, { problem: true });
        continue;
      }
      confirm(item);
    }
  } finally {
    flushing = false;
  }
}

function confirm(item) {
  const mine = pending.find((p) => p.id === item.id);
  if (!mine) return;
  if (isEntryChange(mine.change)) {
    const loaded = mine.dates.filter((d) => days[d]);
    mine.confirmedAt = loadTicket;
    mine.waiting = new Set(loaded);
    if (!loaded.length) pending = pending.filter((p) => p.id !== item.id);
    savePending();
    for (const date of loaded) loadDay(date);
    if (mine.change.kind === 'save' && library) loadLibrary();
  } else {
    mine.confirmedAt = libraryTicket;
    savePending();
    loadLibrary();
    // The training-day threshold changes which days are training days.
    if (mine.change.kind === 'settings-save' && 'training_minutes' in mine.change.record) {
      for (const date of Object.keys(days)) loadDay(date);
    }
  }
}

/** Show a change now and queue it for the server. */
function commit(change, requests, dates = []) {
  pending = [
    ...pending,
    { id: ++counter, change, requests, dates, account: library?.account ?? null, confirmedAt: null, waiting: new Set() },
  ];
  savePending();
  flush();
  return true;
}

// ---------------------------------------------------------------- logging

const datesOf = (entries) => [...new Set(entries.map((e) => e.local_date))];

/** Log entries as one tap, with an undo that takes the whole tap back. */
export function logEntries(entries, message) {
  commit({ kind: 'save', entries }, [{ type: 'entries.save', records: entries, changed_at: now() }], datesOf(entries));
  const groups = [...new Set(entries.map((e) => e.group_id))];
  const offline = !online || navigator.onLine === false;
  showToast(offline ? `${message} · will send when online` : message, {
    undo: () => removeGroups(groups, datesOf(entries)),
  });
  return true;
}

function removeGroups(groupIds, dates) {
  return commit(
    { kind: 'delete-groups', groupIds },
    groupIds.map((groupId) => ({ type: 'group.delete', group_id: groupId, changed_at: now() })),
    dates,
  );
}

/** A preset tap. Returns false when none of its foods are left to log. */
export function logPreset(preset, when) {
  const lib = libraryView();
  const foodsById = new Map((lib?.foods ?? []).map((f) => [f.id, f]));
  const { entries, skipped } = F.presetEntries(preset, foodsById, when);
  if (!entries.length) {
    showToast(`${preset.name} has no foods left to log. Its foods were deleted.`, { problem: true });
    return false;
  }
  const items = `${entries.length} ${entries.length === 1 ? 'item' : 'items'}`;
  logEntries(entries, `${preset.name} logged · ${items}${skipped ? ` · ${skipped} deleted food left out` : ''}`);
  return true;
}

/** Changes to entries already logged: a new amount, or a new time (which can move them to another day). */
export function updateEntries(before, after) {
  return commit(
    { kind: 'save', entries: after },
    [{ type: 'entries.save', records: after, changed_at: now() }],
    [...new Set([...datesOf(before), ...datesOf(after)])],
  );
}

/** Delete entries, with an undo that logs copies of them (a deleted id stays deleted). */
export function deleteEntries(entries, message) {
  const ids = entries.map((e) => e.id);
  commit({ kind: 'delete', ids }, [{ type: 'entries.delete', ids, changed_at: now() }], datesOf(entries));
  showToast(message, {
    undo: () => {
      const back = F.copies(entries);
      commit({ kind: 'save', entries: back }, [{ type: 'entries.save', records: back, changed_at: now() }], datesOf(back));
    },
  });
}

export function setDayType(date, value) {
  return commit(
    { kind: 'day-type', date, value },
    [{ type: 'day_type.set', date, day_type: value, changed_at: now() }],
    [date],
  );
}

// ---------------------------------------------------------------- the library

export function saveFood(record, message = null) {
  commit({ kind: 'food-save', record }, [{ type: 'food.save', record, changed_at: now() }]);
  if (message) showToast(message);
}

export function toggleFavourite(foodId) {
  const record = libraryView()?.foods.find((f) => f.id === foodId);
  if (record) saveFood({ ...$state.snapshot(record), favourite: !record.favourite });
}

/** Past entries keep their own copy, and presets that use it skip it. */
export function deleteFood(record) {
  commit({ kind: 'food-delete', id: record.id }, [{ type: 'food.delete', id: record.id, changed_at: now() }]);
  showToast(`${record.name} deleted`);
}

export function savePreset(preset) {
  const lib = libraryView();
  if (!lib) return false;
  const names = new Map(lib.foods.map((f) => [f.id, f.name]));
  const existing = lib.presets.find((p) => p.id === preset.id);
  const sortOrder = preset.sort_order ?? existing?.sort_order ?? lib.presets.length;
  const shown = {
    id: preset.id,
    name: preset.name,
    sort_order: sortOrder,
    items: preset.items.map((i) => ({ ...i, food_name: names.get(i.food_id) ?? '', food_deleted: false })),
  };
  const record = { id: preset.id, name: preset.name, items: preset.items, sort_order: sortOrder };
  return commit({ kind: 'preset-save', preset: shown }, [{ type: 'preset.save', record, changed_at: now() }]);
}

export function deletePreset(preset) {
  commit({ kind: 'preset-delete', id: preset.id }, [{ type: 'preset.delete', id: preset.id, changed_at: now() }]);
  showToast(`${preset.name} deleted`, {
    undo: () =>
      savePreset({
        id: F.newId(),
        name: preset.name,
        items: preset.items.filter((i) => !i.food_deleted).map(({ food_id, quantity, unit }) => ({ food_id, quantity, unit })),
      }),
  });
}

export function movePreset(preset, direction) {
  const lib = libraryView();
  if (!lib) return;
  const order = [...lib.presets];
  const from = order.findIndex((p) => p.id === preset.id);
  const to = from + direction;
  if (from < 0 || to < 0 || to >= order.length) return;
  [order[from], order[to]] = [order[to], order[from]];
  const ids = order.map((p) => p.id);
  commit({ kind: 'presets-order', ids }, [{ type: 'presets.order', ids, changed_at: now() }]);
}

/** Targets for a day type from a date on. Days before it keep the targets they had. */
export function saveTargets(dayType, effectiveFrom, values) {
  const set = { day_type: dayType, effective_from: effectiveFrom, targets: values };
  return commit({ kind: 'targets-save', set }, [
    { type: 'targets.save', day_type: dayType, effective_from: effectiveFrom, targets: values, changed_at: now() },
  ]);
}

export function saveNutrient(record) {
  commit({ kind: 'nutrient-save', record }, [{ type: 'nutrient.save', record, changed_at: now() }]);
}

export function deleteNutrient(record) {
  commit({ kind: 'nutrient-delete', id: record.id }, [{ type: 'nutrient.delete', id: record.id, changed_at: now() }]);
  showToast(`${record.name} deleted. Values already saved for it are kept but no longer shown.`);
}

export function saveSettings(record) {
  commit({ kind: 'settings-save', record }, [{ type: 'settings.save', record, changed_at: now() }]);
}

/** After an import, read everything back. */
export function refreshAll() {
  loadLibrary();
  for (const date of Object.keys(days)) loadDay(date);
}

export const food = {
  get library() {
    return libraryView();
  },
  get libraryError() {
    return libraryError;
  },
  get toast() {
    return toast;
  },
  get online() {
    return online;
  },
  /** Changes not yet on the server. */
  get waiting() {
    return pending.filter((p) => p.confirmedAt === null).length;
  },
};
