// The food logger's shared state: the library, each loaded day, and changes on their way to the server.
// A tap changes the screen at once. The change then goes to the server, one request at a time and in order, so an
// undo can never overtake the log it undoes. Until the server has the change and the day has been read back,
// it's laid over the last data the server sent, so a reload in between can't make a tap flicker away.
import { get, post } from './api.js';
import * as F from './food.js';

let library = $state(null);
let libraryError = $state(null);
let days = $state({});
let pending = $state([]);
let toast = $state(null);

let counter = 0;
let loadTicket = 0;
const latestLoad = {};
let queue = Promise.resolve();
let toastTimer = null;

const now = () => new Date().toISOString();

// ---------------------------------------------------------------- reading

export async function loadLibrary() {
  try {
    library = await get('/api/food/library');
    libraryError = null;
  } catch (failure) {
    libraryError = failure;
  }
}

export async function loadDay(date) {
  const ticket = ++loadTicket;
  latestLoad[date] = ticket;
  if (!days[date]) days[date] = { data: null, error: null };
  try {
    const data = await get(`/api/food/day?date=${date}`);
    if (latestLoad[date] !== ticket) return;
    days[date] = { data, error: null };
    // A confirmed change can stop being laid over once each day it touched has been read back since.
    pending = pending.filter((item) => {
      if (item.confirmedAt !== null && item.confirmedAt < ticket) item.waiting.delete(date);
      return item.confirmedAt === null || item.waiting.size > 0;
    });
  } catch (failure) {
    if (latestLoad[date] === ticket) days[date] = { data: days[date]?.data ?? null, error: failure };
  }
}

/** One day as the screen shows it: the server's entries with changes still on their way laid over them. */
export function dayView(date) {
  const state = days[date];
  const data = state?.data;
  if (!data) return { date, loaded: false, error: state?.error ?? null };
  const changes = pending.map((item) => item.change);
  const server = data.meals.flatMap((meal) => meal.entries);
  const entries = F.applyChanges(server, changes).filter((e) => e.local_date === date);
  const nutrients = library?.nutrients ?? data.nutrients;
  const sums = F.totals(
    entries,
    nutrients.map((n) => n.id),
  );
  let dayType = { ...data.day_type };
  const chosen = changes.filter((c) => c.kind === 'day-type' && c.date === date).at(-1);
  if (chosen?.value) dayType = { ...dayType, type: chosen.value, how: 'override' };
  const targetSet = library
    ? F.targetsFor(date, dayType.type, library.targets)
    : data.rings.length
      ? { effective_from: data.targets_from, targets: Object.fromEntries(data.rings.map((r) => [r.id, r.target])) }
      : null;
  const eaten = sums.values.kcal ?? 0;
  const burned = data.balance.burned_kcal;
  return {
    date,
    loaded: true,
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

// ---------------------------------------------------------------- writing

/** Send changes after any already on their way. Throws the first change's own error message if one is refused. */
function send(changes) {
  const run = queue.then(() => post('/api/food/changes', { changes }));
  queue = run.catch(() => {});
  return run.then(({ results }) => {
    const refused = results.find((r) => 'error' in r);
    if (refused) throw new Error(refused.error);
    return results.map((r) => r.result);
  });
}

/** Show a change now, send it, then read back the days it touched. If it fails, the screen goes back. */
async function commit(change, requests, dates) {
  const item = { id: ++counter, change, confirmedAt: null, waiting: new Set() };
  pending = [...pending, item];
  try {
    await send(requests);
  } catch (failure) {
    pending = pending.filter((p) => p.id !== item.id);
    showToast(`Not saved. ${failure.message}`, { problem: true });
    return false;
  }
  const loaded = dates.filter((d) => days[d]);
  const mine = pending.find((p) => p.id === item.id);
  if (mine) {
    mine.confirmedAt = loadTicket;
    mine.waiting = new Set(loaded);
    if (!loaded.length) pending = pending.filter((p) => p.id !== item.id);
  }
  await Promise.all(loaded.map(loadDay));
  return true;
}

const datesOf = (entries) => [...new Set(entries.map((e) => e.local_date))];

/** Log entries as one tap, with an undo that takes the whole tap back. */
export function logEntries(entries, message) {
  const done = commit(
    { kind: 'save', entries },
    [{ type: 'entries.save', records: entries, changed_at: now() }],
    datesOf(entries),
  ).then((ok) => {
    if (ok && library) loadLibrary();
    return ok;
  });
  const groups = [...new Set(entries.map((e) => e.group_id))];
  showToast(message, { undo: () => removeGroups(groups, datesOf(entries)) });
  return done;
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
  const foodsById = new Map((library?.foods ?? []).map((f) => [f.id, f]));
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
  const done = commit(
    { kind: 'delete', ids },
    [{ type: 'entries.delete', ids, changed_at: now() }],
    datesOf(entries),
  );
  showToast(message, {
    undo: () => {
      const back = F.copies(entries);
      commit({ kind: 'save', entries: back }, [{ type: 'entries.save', records: back, changed_at: now() }], datesOf(back));
    },
  });
  return done;
}

export function setDayType(date, value) {
  return commit(
    { kind: 'day-type', date, value },
    [{ type: 'day_type.set', date, day_type: value, changed_at: now() }],
    [date],
  );
}

// Library changes show at once too, then the library is read back.
async function changeLibrary(requests, problemPrefix = 'Not saved.') {
  try {
    await send(requests);
    return true;
  } catch (failure) {
    showToast(`${problemPrefix} ${failure.message}`, { problem: true });
    return false;
  } finally {
    await loadLibrary();
  }
}

export function toggleFavourite(foodId) {
  const record = library?.foods.find((f) => f.id === foodId);
  if (!record) return;
  record.favourite = !record.favourite;
  changeLibrary([{ type: 'food.save', record: { ...record }, changed_at: now() }]);
}

export function savePreset(preset) {
  if (!library) return Promise.resolve(false);
  const names = new Map(library.foods.map((f) => [f.id, f.name]));
  const shown = {
    ...preset,
    sort_order: preset.sort_order ?? library.presets.length,
    items: preset.items.map((i) => ({ ...i, food_name: names.get(i.food_id) ?? '', food_deleted: false })),
  };
  const others = library.presets.filter((p) => p.id !== preset.id);
  library.presets = [...others, shown].sort((a, b) => a.sort_order - b.sort_order);
  const record = { id: preset.id, name: preset.name, items: preset.items, sort_order: shown.sort_order };
  return changeLibrary([{ type: 'preset.save', record, changed_at: now() }]);
}

export function deletePreset(preset) {
  if (!library) return;
  library.presets = library.presets.filter((p) => p.id !== preset.id);
  changeLibrary([{ type: 'preset.delete', id: preset.id, changed_at: now() }]);
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
  if (!library) return;
  const order = [...library.presets];
  const from = order.findIndex((p) => p.id === preset.id);
  const to = from + direction;
  if (from < 0 || to < 0 || to >= order.length) return;
  [order[from], order[to]] = [order[to], order[from]];
  library.presets = order.map((p, i) => ({ ...p, sort_order: i }));
  changeLibrary([{ type: 'presets.order', ids: order.map((p) => p.id), changed_at: now() }]);
}

/** Targets for a day type from a date on. Days before it keep the targets they had. */
export function saveTargets(dayType, effectiveFrom, values) {
  if (!library) return Promise.resolve(false);
  const set = { day_type: dayType, effective_from: effectiveFrom, targets: values };
  library.targets = [
    ...library.targets.filter((t) => !(t.day_type === dayType && t.effective_from === effectiveFrom)),
    set,
  ];
  return changeLibrary([
    { type: 'targets.save', day_type: dayType, effective_from: effectiveFrom, targets: values, changed_at: now() },
  ]);
}

export const food = {
  get library() {
    return library;
  },
  get libraryError() {
    return libraryError;
  },
  get toast() {
    return toast;
  },
  get sending() {
    return pending.some((p) => p.confirmedAt === null);
  },
};
