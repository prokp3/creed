// The food logger's arithmetic, done on the phone so a tap shows straight away. It mirrors creed/food on the
// server: values are per 100 of a food's base (g, or ml for a liquid), a quantity in any unit becomes an amount of
// the base, and a nutrient a food doesn't list is unknown, not zero. Pure functions, tested in food.test.js.
import { pad2 } from './format.js';

export const QUICK_ADD = 'Quick add';
// A one-off food has no weight, so it's stored as one 1,000 g serving: values per 100 are a tenth of what was typed.
// The big serving keeps the per-100 limits (1,000 kcal per 100 g) from refusing a large restaurant meal.
export const ONE_OFF_UNIT = 'serving';
export const ONE_OFF_GRAMS = 1000;

const SAME_IN_PLURAL = new Set(['g', 'ml', 'tbsp', 'tsp', 'oz']);

let lastMs = 0;
let sequence = 0;

/**
 * A new id, made on the phone so a tap can be sent again without logging it twice. Ids are time-ordered (UUID
 * version 7), so foods logged together keep the order they were tapped in: the server sorts ties by id.
 */
export function newId() {
  let ms = Date.now();
  if (ms <= lastMs) {
    sequence += 1;
    if (sequence > 0xfff) {
      lastMs += 1;
      sequence = 0;
    }
    ms = lastMs;
  } else {
    lastMs = ms;
    sequence = 0;
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  for (let i = 5; i >= 0; i -= 1) {
    bytes[i] = ms % 256;
    ms = Math.floor(ms / 256);
  }
  bytes[6] = 0x70 | (sequence >> 8);
  bytes[7] = sequence & 0xff;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// ---------------------------------------------------------------- dates and times on this phone

/** This phone's date for an instant, as 2026-11-06. */
export function localDate(when = new Date()) {
  return `${when.getFullYear()}-${pad2(when.getMonth() + 1)}-${pad2(when.getDate())}`;
}

export function addDays(isoDate, days) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return localDate(new Date(year, month - 1, day + days));
}

/** An instant with this phone's offset, such as 2026-11-06T20:00:00+05:30, which the server needs to place it. */
export function withOffset(when) {
  const offset = -when.getTimezoneOffset();
  const sign = offset >= 0 ? '+' : '-';
  const abs = Math.abs(offset);
  return (
    `${localDate(when)}T${pad2(when.getHours())}:${pad2(when.getMinutes())}:${pad2(when.getSeconds())}` +
    `${sign}${pad2(Math.floor(abs / 60))}:${pad2(abs % 60)}`
  );
}

/** A clock time on a date, on this phone: the time a meal on a past day is logged at. */
export function at(isoDate, hours, minutes) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return new Date(year, month - 1, day, hours, minutes, 0, 0);
}

/** 8:05 PM */
export function clockText(when) {
  const hours = when.getHours();
  return `${hours % 12 || 12}:${pad2(when.getMinutes())} ${hours < 12 ? 'AM' : 'PM'}`;
}

// ---------------------------------------------------------------- units and scaling

export function unitAmount(unit, base, units = {}) {
  if (unit === base) return 1;
  if (Object.hasOwn(units, unit)) return Number(units[unit]);
  throw new Error(`This food can't be measured in ${unit}.`);
}

export const baseAmount = (quantity, unit, base, units) => quantity * unitAmount(unit, base, units);

export function scale(per100, amount) {
  const values = {};
  for (const [key, value] of Object.entries(per100)) values[key] = (value * amount) / 100;
  return values;
}

export const entryNutrients = (entry) => scale(entry.nutrients_per_100, entry.base_amount);

/** The units a food can be logged in: its usual one first, then its others, then its base. */
export function unitChoices(food) {
  return [...new Set([food.default_unit, ...Object.keys(food.units ?? {}), food.base])];
}

/** One of a unit, or 100 g / ml, which is how labels list values. */
export const startingQuantity = (unit, base) => (unit === base ? 100 : 1);

/** How far the − and + buttons move: a gram at a time would take all day. */
export const quantityStep = (unit, base) => (unit === base ? 10 : 1);

/** The next whole step up or down: 6.5 pieces goes to 7 or 6, and 155 g to 160 or 150. */
export function stepQuantity(quantity, unit, base, direction) {
  const step = quantityStep(unit, base);
  const next = direction > 0 ? Math.floor(quantity / step + 1e-9) * step + step : Math.ceil(quantity / step - 1e-9) * step - step;
  return Math.max(step === 1 ? 0.5 : step, next);
}

/** The same amount of food in another unit, rounded to half a unit or a whole gram. */
export function convertQuantity(quantity, fromUnit, toUnit, base, units) {
  const exact = baseAmount(quantity, fromUnit, base, units) / unitAmount(toUnit, base, units);
  const grain = toUnit === base ? 1 : 0.5;
  return Math.max(grain, Math.round(exact / grain) * grain);
}

/** Up to one decimal, without a trailing .0: 6, 1.5, 37.8. */
export function number(value) {
  if (!Number.isFinite(value)) return '—';
  const rounded = Math.round(value * 10) / 10;
  return rounded.toLocaleString('en-IN', { maximumFractionDigits: 1 });
}

/** 6 pieces, 1 scoop, 2 glasses, 150 g. */
export function quantityText(quantity, unit) {
  if (SAME_IN_PLURAL.has(unit) || quantity === 1) return `${number(quantity)} ${unit}`;
  const plural = /(s|x|ch|sh)$/.test(unit) ? `${unit}es` : `${unit}s`;
  return `${number(quantity)} ${plural}`;
}

/** A nutrient amount the way it's read: whole kcal and mg, grams to a decimal when small. */
export function amountText(value, unit) {
  if (!Number.isFinite(value)) return '—';
  if (unit === 'kcal' || unit === 'mg') return Math.round(value).toLocaleString('en-IN');
  return value < 10 ? number(value) : Math.round(value).toLocaleString('en-IN');
}

// ---------------------------------------------------------------- building entries

/** An entry for a food from the library, with its own copy of the food so later edits change no past day. */
export function entryFromFood(food, { quantity, unit, when, groupId, kind = 'quick', mealLabel = null, presetId = null }) {
  const id = newId();
  const units = { ...(food.units ?? {}) };
  return {
    id,
    group_id: groupId ?? id,
    kind,
    preset_id: presetId,
    meal_label: mealLabel ?? (kind === 'quick' ? QUICK_ADD : null),
    food_id: food.id,
    logged_at: withOffset(when),
    utc_offset_minutes: -when.getTimezoneOffset(),
    local_date: localDate(when),
    quantity,
    unit,
    base_amount: baseAmount(quantity, unit, food.base, units),
    food_name: food.name,
    food_brand: food.brand ?? null,
    base: food.base,
    nutrients_per_100: { ...food.nutrients },
    unit_amounts: units,
  };
}

/** Something eaten once, with values for the whole thing. Blank values stay unknown. */
export function oneOffEntry({ name, values, when }) {
  const id = newId();
  const per100 = {};
  for (const [key, value] of Object.entries(values)) {
    if (Number.isFinite(value)) per100[key] = (value * 100) / ONE_OFF_GRAMS;
  }
  return {
    id,
    group_id: id,
    kind: 'quick',
    preset_id: null,
    meal_label: QUICK_ADD,
    food_id: null,
    logged_at: withOffset(when),
    utc_offset_minutes: -when.getTimezoneOffset(),
    local_date: localDate(when),
    quantity: 1,
    unit: ONE_OFF_UNIT,
    base_amount: ONE_OFF_GRAMS,
    food_name: name,
    food_brand: null,
    base: 'g',
    nutrients_per_100: per100,
    unit_amounts: { [ONE_OFF_UNIT]: ONE_OFF_GRAMS },
  };
}

export const isOneOff = (entry) => entry.food_id === null && entry.unit === ONE_OFF_UNIT;

/** One tap on a preset: every food in it, logged together as one meal. Foods since deleted are left out. */
export function presetEntries(preset, foodsById, when) {
  const groupId = newId();
  const entries = [];
  let skipped = 0;
  for (const item of preset.items) {
    const food = foodsById.get(item.food_id);
    if (!food || item.food_deleted) {
      skipped += 1;
      continue;
    }
    try {
      entries.push(
        entryFromFood(food, {
          quantity: item.quantity,
          unit: item.unit,
          when,
          groupId,
          kind: 'preset',
          mealLabel: preset.name,
          presetId: preset.id,
        }),
      );
    } catch {
      // The food lost the unit this preset uses since the preset was made.
      skipped += 1;
    }
  }
  return { entries, skipped, groupId };
}

/** The same entry with a new quantity, worked out from its own copy of the food. */
export function withQuantity(entry, quantity, unit) {
  return { ...entry, quantity, unit, base_amount: baseAmount(quantity, unit, entry.base, entry.unit_amounts) };
}

/** The same entry at another time, which can move it to another day. */
export function atTime(entry, when) {
  return {
    ...entry,
    logged_at: withOffset(when),
    utc_offset_minutes: -when.getTimezoneOffset(),
    local_date: localDate(when),
  };
}

/** A copy with new ids, to bring back something deleted (a deleted id stays deleted, by the sync rules). */
export function copies(entries) {
  const groups = new Map();
  return entries.map((entry) => {
    if (!groups.has(entry.group_id)) groups.set(entry.group_id, newId());
    return { ...entry, id: newId(), group_id: groups.get(entry.group_id) };
  });
}

// ---------------------------------------------------------------- a day

/** Changes not yet confirmed by the server, laid over what it last sent. Applying one twice changes nothing. */
export function applyChanges(entries, changes) {
  let result = entries;
  for (const change of changes) {
    if (change.kind === 'save') {
      const byId = new Map(result.map((e) => [e.id, e]));
      for (const entry of change.entries) byId.set(entry.id, entry);
      result = [...byId.values()];
    } else if (change.kind === 'delete') {
      const ids = new Set(change.ids);
      result = result.filter((e) => !ids.has(e.id));
    } else if (change.kind === 'delete-groups') {
      const groups = new Set(change.groupIds);
      result = result.filter((e) => !groups.has(e.group_id));
    }
  }
  return result;
}

const byTime = (a, b) => Date.parse(a.logged_at) - Date.parse(b.logged_at) || (a.id < b.id ? -1 : 1);

/** Entries logged together (one preset tap, or one quick add) are a meal, in order of the meal's first entry. */
export function meals(entries) {
  const groups = new Map();
  for (const entry of [...entries].sort(byTime)) {
    let meal = groups.get(entry.group_id);
    if (!meal) {
      meal = {
        group_id: entry.group_id,
        label: entry.meal_label,
        kind: entry.kind,
        preset_id: entry.preset_id,
        logged_at: entry.logged_at,
        entries: [],
        totals: {},
      };
      groups.set(entry.group_id, meal);
    }
    meal.entries.push(entry);
    for (const [key, value] of Object.entries(entryNutrients(entry))) {
      meal.totals[key] = (meal.totals[key] ?? 0) + value;
    }
  }
  return [...groups.values()].sort((a, b) => Date.parse(a.logged_at) - Date.parse(b.logged_at));
}

/** Sums for each nutrient, and which ones had an entry that didn't list them (so the sum may be low). */
export function totals(entries, nutrientIds) {
  const values = Object.fromEntries(nutrientIds.map((id) => [id, 0]));
  const incomplete = new Set();
  for (const entry of entries) {
    const own = entryNutrients(entry);
    for (const id of nutrientIds) {
      if (id in own) values[id] += own[id];
      else incomplete.add(id);
    }
  }
  return { values, incomplete };
}

/** The newest target set of that day type starting on or before the day. */
export function targetsFor(isoDate, dayType, sets) {
  let best = null;
  for (const set of sets ?? []) {
    if (set.day_type === dayType && set.effective_from <= isoDate && (!best || set.effective_from > best.effective_from)) {
      best = set;
    }
  }
  return best;
}

/** Every nutrient with its eaten amount and, when it has one, its target. */
export function progress(nutrients, dayTotals, targetSet) {
  return nutrients.map((n) => {
    const eaten = dayTotals.values[n.id] ?? 0;
    const target = targetSet?.targets?.[n.id] ?? null;
    return {
      id: n.id,
      name: n.name,
      unit: n.unit,
      eaten,
      target,
      remaining: target === null ? null : target - eaten,
      fraction: target ? eaten / target : 0,
      incomplete: dayTotals.incomplete.has(n.id),
    };
  });
}

/** Which entries gave a nutrient, biggest first: what a ring's detail lists. */
export function contributions(entries, nutrientId) {
  return entries
    .map((entry) => ({ entry, value: entryNutrients(entry)[nutrientId] }))
    .filter((row) => Number.isFinite(row.value) && row.value > 0)
    .sort((a, b) => b.value - a.value);
}

/** What a meal row says under its name: the time and what was in it. */
export function mealSummary(meal) {
  const names = meal.entries.map((e) => (meal.entries.length === 1 && !isOneOff(e) ? `${e.food_name}, ${quantityText(e.quantity, e.unit)}` : e.food_name));
  return names.join(', ');
}

// ---------------------------------------------------------------- the library

const normalise = (text) => (text ?? '').toLocaleLowerCase('en-IN').normalize('NFKD').replace(/[̀-ͯ]/g, '');

/** Foods matching a search, names starting with it first. With no search: favourites, then recent ones. */
export function searchFoods(foods, query, recentIds = []) {
  const q = normalise(query).trim();
  if (!q) {
    const recent = new Map(recentIds.map((id, i) => [id, i]));
    return foods
      .filter((f) => f.favourite || recent.has(f.id))
      .sort((a, b) => Number(b.favourite) - Number(a.favourite) || (recent.get(a.id) ?? 99) - (recent.get(b.id) ?? 99));
  }
  const words = q.split(/\s+/);
  const scored = [];
  for (const food of foods) {
    const name = normalise(food.name);
    const text = `${name} ${normalise(food.brand)}`;
    if (!words.every((w) => text.includes(w))) continue;
    const score = name.startsWith(q) ? 0 : name.split(/[\s,]+/).some((part) => part.startsWith(words[0])) ? 1 : 2;
    scored.push({ food, score });
  }
  return scored
    .sort((a, b) => a.score - b.score || Number(b.food.favourite) - Number(a.food.favourite) || a.food.name.localeCompare(b.food.name))
    .map((s) => s.food);
}

/** A preset made from a logged meal: the same foods and amounts. One-off foods can't be part of one. */
export function presetFromMeal(meal, name, foodsById) {
  const items = meal.entries
    .filter((e) => e.food_id && foodsById.has(e.food_id))
    .map((e) => ({ food_id: e.food_id, quantity: e.quantity, unit: e.unit }));
  return { id: newId(), name, items, left_out: meal.entries.length - items.length };
}

// ---------------------------------------------------------------- library changes not yet confirmed

const byName = (a, b) => Number(b.favourite) - Number(a.favourite) || a.name.localeCompare(b.name);
const byOrder = (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name);

function upsert(list, record) {
  const others = list.filter((item) => item.id !== record.id);
  return [...others, record];
}

/** Library changes still on their way, laid over the library the server last sent. Doing it twice changes nothing. */
export function applyLibraryChanges(library, changes) {
  if (!library) return library;
  let { foods, presets, targets, nutrients, settings } = library;
  for (const change of changes) {
    if (change.kind === 'food-save') foods = upsert(foods, change.record);
    else if (change.kind === 'food-delete') {
      foods = foods.filter((f) => f.id !== change.id);
      presets = presets.map((p) => ({
        ...p,
        items: p.items.map((i) => (i.food_id === change.id ? { ...i, food_deleted: true } : i)),
      }));
    } else if (change.kind === 'preset-save') presets = upsert(presets, change.preset);
    else if (change.kind === 'preset-delete') presets = presets.filter((p) => p.id !== change.id);
    else if (change.kind === 'presets-order') {
      const order = new Map(change.ids.map((id, i) => [id, i]));
      presets = presets.map((p) => (order.has(p.id) ? { ...p, sort_order: order.get(p.id) } : p));
    } else if (change.kind === 'targets-save') {
      const set = change.set;
      targets = [...targets.filter((t) => !(t.day_type === set.day_type && t.effective_from === set.effective_from)), set];
    } else if (change.kind === 'nutrient-save') nutrients = upsert(nutrients, change.record);
    else if (change.kind === 'nutrient-delete') nutrients = nutrients.filter((n) => n.id !== change.id);
    else if (change.kind === 'settings-save') settings = { ...settings, ...change.record };
  }
  return {
    ...library,
    foods: [...foods].sort(byName),
    presets: [...presets].sort(byOrder),
    targets,
    nutrients: [...nutrients].sort(byOrder),
    settings,
  };
}

// ---------------------------------------------------------------- foods you make

/** The most of a nutrient 100 g can hold, by unit, as the server checks. */
export function limitPer100(unit) {
  return { kcal: 1000, g: 150, mg: 100000 }[unit] ?? 100000;
}

/**
 * A food record from what was typed: values for `valuesPer` (100 of the base, or one of a unit) become values per
 * 100 of the base. Returns { record } or { problem } with a message for the person.
 */
export function foodFromForm(form, nutrients) {
  const name = form.name.trim();
  if (!name) return { problem: 'Give the food a name.' };
  if (name.length > 80) return { problem: 'Names can be up to 80 characters.' };
  const barcode = form.barcode.trim();
  if (barcode && !/^\d{6,14}$/.test(barcode)) return { problem: 'A barcode is 6 to 14 digits.' };
  const units = {};
  for (const unit of form.units) {
    const unitName = unit.name.trim();
    if (!unitName) continue;
    if (unitName === 'g' || unitName === 'ml') return { problem: `${unitName} is built in, so it doesn't need adding.` };
    if (unitName.length > 20) return { problem: 'Unit names can be up to 20 characters.' };
    if (!(unit.amount > 0)) return { problem: `Say how many ${form.base} one ${unitName} is.` };
    units[unitName] = unit.amount;
  }
  const per = form.valuesPer === form.base ? 100 : units[form.valuesPer];
  if (!per) return { problem: 'Choose what the values are for.' };
  const values = {};
  for (const n of nutrients) {
    const typed = form.values[n.id];
    if (typed === null || typed === undefined || typed === '') continue;
    if (!Number.isFinite(typed) || typed < 0) return { problem: `${n.name} must be a number.` };
    const per100 = (typed * 100) / per;
    if (per100 > limitPer100(n.unit)) {
      return { problem: `${n.name} is more than 100 ${form.base} can hold (${limitPer100(n.unit).toLocaleString('en-IN')} ${n.unit}). Check the amount.` };
    }
    values[n.id] = per100;
  }
  const defaultUnit = form.defaultUnit in units || form.defaultUnit === form.base ? form.defaultUnit : form.base;
  return {
    record: {
      id: form.id,
      name,
      brand: form.brand.trim() || null,
      barcode: barcode || null,
      base: form.base,
      nutrients: values,
      units,
      default_unit: defaultUnit,
      favourite: Boolean(form.favourite),
      source: form.source ?? 'manual',
      notes: form.notes.trim() || null,
    },
  };
}

/** The editing form for a food: blank, an existing one, a copy, or a scanned draft. Values start per 100. */
export function formFromFood(food, base = 'g') {
  const source = food ?? {};
  const values = {};
  for (const [key, value] of Object.entries(source.nutrients ?? {})) values[key] = Math.round(value * 100) / 100;
  return {
    id: source.id ?? newId(),
    name: source.name ?? '',
    brand: source.brand ?? '',
    barcode: source.barcode ?? '',
    base: source.base ?? base,
    units: Object.entries(source.units ?? {}).map(([name, amount]) => ({ name, amount })),
    defaultUnit: source.default_unit ?? source.base ?? base,
    valuesPer: source.base ?? base,
    values,
    favourite: Boolean(source.favourite),
    source: source.source ?? 'manual',
    notes: source.notes ?? '',
  };
}

/** Shown values when switching what they're for: per 100 g to per 30 g scoop, and back. */
export function convertValues(values, fromAmount, toAmount) {
  const out = {};
  for (const [key, value] of Object.entries(values)) {
    out[key] = Number.isFinite(value) ? Math.round(((value * toAmount) / fromAmount) * 100) / 100 : value;
  }
  return out;
}
