import { describe, expect, it } from 'vitest';
import {
  addDays,
  amountText,
  applyChanges,
  applyLibraryChanges,
  baseAmount,
  clockText,
  contributions,
  convertQuantity,
  convertValues,
  copies,
  entryFromFood,
  entryNutrients,
  foodFromForm,
  formFromFood,
  localDate,
  mealSummary,
  meals,
  newId,
  scheduleText,
  supplementsDay,
  weekStart,
  weekday,
  oneOffEntry,
  presetEntries,
  presetFromMeal,
  progress,
  quantityText,
  searchFoods,
  stepQuantity,
  targetsFor,
  totals,
  unitChoices,
  withOffset,
  withQuantity,
} from './food.js';
import { checkDigitOk } from './scanner.js';

const EGG = {
  id: 'egg',
  name: 'Egg, whole',
  brand: null,
  base: 'g',
  nutrients: { kcal: 143, protein: 12.6, carbs: 0.7, fat: 9.5, sodium: 142 },
  units: { piece: 50 },
  default_unit: 'piece',
  favourite: false,
};
const MILK = {
  id: 'milk',
  name: 'Milk, toned',
  brand: 'Amul',
  base: 'ml',
  nutrients: { kcal: 58, protein: 3.1 },
  units: { glass: 250, cup: 240 },
  default_unit: 'glass',
  favourite: true,
};
const OATS = { id: 'oats', name: 'Oats', base: 'g', nutrients: { kcal: 389, protein: 16.9 }, units: {}, default_unit: 'g', favourite: false };
const NUTRIENTS = [
  { id: 'kcal', name: 'Calories', unit: 'kcal' },
  { id: 'protein', name: 'Protein', unit: 'g' },
  { id: 'sodium', name: 'Sodium', unit: 'mg' },
];
const EIGHT_PM = new Date(2026, 10, 6, 20, 0);

describe('units and amounts', () => {
  it('turns six pieces of a 50 g egg into 300 g', () => {
    expect(baseAmount(6, 'piece', 'g', EGG.units)).toBe(300);
    expect(baseAmount(150, 'g', 'g', EGG.units)).toBe(150);
    expect(() => baseAmount(1, 'scoop', 'g', EGG.units)).toThrow();
  });

  it('offers the usual unit first and the base last', () => {
    expect(unitChoices(MILK)).toEqual(['glass', 'cup', 'ml']);
    expect(unitChoices(OATS)).toEqual(['g']);
  });

  it('steps to whole numbers of pieces and tens of grams', () => {
    expect(stepQuantity(6, 'piece', 'g', 1)).toBe(7);
    expect(stepQuantity(6.5, 'piece', 'g', 1)).toBe(7);
    expect(stepQuantity(6.5, 'piece', 'g', -1)).toBe(6);
    expect(stepQuantity(155, 'g', 'g', 1)).toBe(160);
    expect(stepQuantity(155, 'g', 'g', -1)).toBe(150);
    expect(stepQuantity(1, 'piece', 'g', -1)).toBe(0.5);
    expect(stepQuantity(10, 'g', 'g', -1)).toBe(10);
  });

  it('keeps the same food when switching units', () => {
    expect(convertQuantity(6, 'piece', 'g', 'g', EGG.units)).toBe(300);
    expect(convertQuantity(130, 'g', 'piece', 'g', EGG.units)).toBe(2.5);
    expect(convertQuantity(1, 'glass', 'cup', 'ml', MILK.units)).toBe(1);
  });

  it('writes amounts the way they are said', () => {
    expect(quantityText(6, 'piece')).toBe('6 pieces');
    expect(quantityText(1, 'scoop')).toBe('1 scoop');
    expect(quantityText(2, 'glass')).toBe('2 glasses');
    expect(quantityText(150, 'g')).toBe('150 g');
    expect(quantityText(2, 'tbsp')).toBe('2 tbsp');
    expect(quantityText(1.5, 'katori')).toBe('1.5 katoris');
    expect(amountText(1640.4, 'kcal')).toBe('1,640');
    expect(amountText(37.84, 'g')).toBe('38');
    expect(amountText(2.14, 'g')).toBe('2.1');
    expect(amountText(426.2, 'mg')).toBe('426');
  });
});

describe('dates on the phone', () => {
  it('writes an instant with this phone’s offset', () => {
    expect(withOffset(EIGHT_PM)).toMatch(/^2026-11-06T20:00:00[+-]\d\d:\d\d$/);
    expect(Date.parse(withOffset(EIGHT_PM))).toBe(EIGHT_PM.getTime());
  });

  it('moves between days across month ends', () => {
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(localDate(EIGHT_PM)).toBe('2026-11-06');
    expect(clockText(EIGHT_PM)).toBe('8:00 PM');
    expect(clockText(new Date(2026, 10, 6, 0, 5))).toBe('12:05 AM');
  });
});

describe('ids', () => {
  it('makes valid, time-ordered ids, so things tapped together keep their order', () => {
    const ids = Array.from({ length: 50 }, () => newId());
    expect(ids.every((id) => /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id))).toBe(true);
    expect([...ids].sort()).toEqual(ids);
    expect(new Set(ids).size).toBe(50);
  });
});

describe('entries', () => {
  it('logs six eggs as 429 kcal and 37.8 g of protein, like the server', () => {
    const entry = entryFromFood(EGG, { quantity: 6, unit: 'piece', when: EIGHT_PM });
    expect(entry.base_amount).toBe(300);
    expect(entry.kind).toBe('quick');
    expect(entry.meal_label).toBe('Quick add');
    expect(entry.group_id).toBe(entry.id);
    expect(entry.local_date).toBe('2026-11-06');
    const values = entryNutrients(entry);
    expect(values.kcal).toBeCloseTo(429);
    expect(values.protein).toBeCloseTo(37.8);
  });

  it('keeps its own copy of the food', () => {
    const food = structuredClone(EGG);
    const entry = entryFromFood(food, { quantity: 1, unit: 'piece', when: EIGHT_PM });
    food.nutrients.kcal = 999;
    food.units.piece = 99;
    expect(entryNutrients(entry).kcal).toBeCloseTo(71.5);
  });

  it('gives back exactly what was typed for a one-off, and leaves blanks unknown', () => {
    const entry = oneOffEntry({ name: 'Masala dosa', values: { kcal: 1450, protein: 9, sodium: undefined }, when: EIGHT_PM });
    expect(entry.food_id).toBeNull();
    const values = entryNutrients(entry);
    expect(values.kcal).toBeCloseTo(1450);
    expect(values.protein).toBeCloseTo(9);
    expect('sodium' in values).toBe(false);
    // Per 100 g stays under the server's 1,000 kcal limit even for a big meal.
    expect(entry.nutrients_per_100.kcal).toBeLessThanOrEqual(1000);
  });

  it('changes an amount from the entry’s own copy', () => {
    const entry = entryFromFood(EGG, { quantity: 6, unit: 'piece', when: EIGHT_PM });
    const edited = withQuantity(entry, 120, 'g');
    expect(edited.id).toBe(entry.id);
    expect(edited.base_amount).toBe(120);
  });

  it('logs a preset as one meal and leaves out deleted foods', () => {
    const preset = {
      id: 'p1',
      name: 'Breakfast',
      items: [
        { food_id: 'oats', quantity: 80, unit: 'g' },
        { food_id: 'milk', quantity: 1, unit: 'glass' },
        { food_id: 'gone', quantity: 1, unit: 'g', food_deleted: true },
      ],
    };
    const foods = new Map([OATS, MILK].map((f) => [f.id, f]));
    const { entries, skipped, groupId } = presetEntries(preset, foods, EIGHT_PM);
    expect(entries).toHaveLength(2);
    expect(skipped).toBe(1);
    expect(entries.every((e) => e.group_id === groupId && e.kind === 'preset' && e.meal_label === 'Breakfast' && e.preset_id === 'p1')).toBe(true);
    expect(new Set(entries.map((e) => e.id)).size).toBe(2);
  });

  it('brings back deleted entries under new ids, keeping them together', () => {
    const a = entryFromFood(EGG, { quantity: 2, unit: 'piece', when: EIGHT_PM, groupId: 'g' });
    const b = entryFromFood(MILK, { quantity: 1, unit: 'glass', when: EIGHT_PM, groupId: 'g' });
    const [ca, cb] = copies([a, b]);
    expect(ca.id).not.toBe(a.id);
    expect(ca.group_id).not.toBe('g');
    expect(ca.group_id).toBe(cb.group_id);
  });
});

describe('a day', () => {
  const morning = new Date(2026, 10, 6, 7, 40);
  const lunch = new Date(2026, 10, 6, 13, 30);
  const oats = entryFromFood(OATS, { quantity: 80, unit: 'g', when: morning, groupId: 'b', kind: 'preset', mealLabel: 'Breakfast' });
  const milk = entryFromFood(MILK, { quantity: 1, unit: 'glass', when: morning, groupId: 'b', kind: 'preset', mealLabel: 'Breakfast' });
  const eggs = entryFromFood(EGG, { quantity: 3, unit: 'piece', when: lunch });

  it('lays unconfirmed changes over the server’s entries, and doing so twice changes nothing', () => {
    const changes = [
      { kind: 'save', entries: [eggs] },
      { kind: 'delete', ids: [milk.id] },
    ];
    const once = applyChanges([oats, milk], changes);
    expect(once.map((e) => e.id).sort()).toEqual([oats.id, eggs.id].sort());
    expect(applyChanges(once, changes)).toEqual(once);
    expect(applyChanges([oats, milk, eggs], [{ kind: 'delete-groups', groupIds: ['b'] }])).toEqual([eggs]);
  });

  it('groups a preset tap into one meal, in time order', () => {
    const day = meals([eggs, milk, oats]);
    expect(day.map((m) => m.label)).toEqual(['Breakfast', 'Quick add']);
    expect(day[0].entries).toHaveLength(2);
    expect(day[0].totals.kcal).toBeCloseTo(389 * 0.8 + 58 * 2.5);
    expect(mealSummary(day[0])).toBe('Oats, Milk, toned');
    expect(mealSummary(day[1])).toBe('Egg, whole, 3 pieces');
  });

  it('says which totals may be low because a food didn’t list them', () => {
    const sums = totals([oats, eggs], ['kcal', 'protein', 'sodium']);
    expect(sums.values.kcal).toBeCloseTo(389 * 0.8 + 143 * 1.5);
    expect(sums.values.sodium).toBeCloseTo(142 * 1.5);
    expect([...sums.incomplete]).toEqual(['sodium']);
  });

  it('uses the newest target set of that day type that had started', () => {
    const sets = [
      { day_type: 'training', effective_from: '2026-11-01', targets: { kcal: 3000 } },
      { day_type: 'training', effective_from: '2026-11-07', targets: { kcal: 3200 } },
      { day_type: 'rest', effective_from: '2026-10-01', targets: { kcal: 2400 } },
    ];
    expect(targetsFor('2026-11-06', 'training', sets).targets.kcal).toBe(3000);
    expect(targetsFor('2026-11-07', 'training', sets).targets.kcal).toBe(3200);
    expect(targetsFor('2026-11-06', 'rest', sets).targets.kcal).toBe(2400);
    expect(targetsFor('2026-09-01', 'rest', sets)).toBeNull();
  });

  it('shows progress against a target, and no made-up target where there is none', () => {
    const sums = totals([eggs], ['kcal', 'protein', 'sodium']);
    const rows = progress(NUTRIENTS, sums, { targets: { kcal: 3000, protein: 160 } });
    const kcal = rows.find((r) => r.id === 'kcal');
    expect(kcal.remaining).toBeCloseTo(3000 - 214.5);
    expect(kcal.fraction).toBeCloseTo(214.5 / 3000);
    const sodium = rows.find((r) => r.id === 'sodium');
    expect(sodium.target).toBeNull();
    expect(sodium.remaining).toBeNull();
    expect(sodium.fraction).toBe(0);
    expect(progress(NUTRIENTS, sums, null).every((r) => r.target === null)).toBe(true);
  });

  it('lists where a nutrient came from, biggest first', () => {
    const rows = contributions([oats, milk, eggs], 'protein');
    expect(rows.map((r) => r.entry.food_name)).toEqual(['Egg, whole', 'Oats', 'Milk, toned']);
    expect(contributions([oats], 'sodium')).toEqual([]);
  });

  it('makes a preset from a meal, without one-off foods', () => {
    const once = oneOffEntry({ name: 'Chai', values: { kcal: 90 }, when: morning });
    const meal = meals([oats, milk, { ...once, group_id: 'b' }])[0];
    const preset = presetFromMeal(meal, 'Breakfast', new Map([OATS, MILK].map((f) => [f.id, f])));
    expect(preset.items).toEqual([
      { food_id: 'oats', quantity: 80, unit: 'g' },
      { food_id: 'milk', quantity: 1, unit: 'glass' },
    ]);
    expect(preset.left_out).toBe(1);
  });
});

describe('search', () => {
  const foods = [EGG, MILK, OATS, { ...EGG, id: 'white', name: 'Egg white', favourite: false }];

  it('shows favourites, then recent foods, when nothing is typed', () => {
    expect(searchFoods(foods, '', ['oats', 'egg']).map((f) => f.id)).toEqual(['milk', 'oats', 'egg']);
  });

  it('puts names that start with the search first, and matches brands', () => {
    expect(searchFoods(foods, 'egg').map((f) => f.id).sort()).toEqual(['egg', 'white']);
    expect(searchFoods(foods, 'oat').map((f) => f.id)).toEqual(['oats']);
    expect(searchFoods([{ ...OATS, name: 'Coconut water' }, { ...OATS, id: 'w', name: 'Water' }], 'wat').map((f) => f.id)).toEqual(['w', 'oats']);
    expect(searchFoods(foods, 'white').map((f) => f.id)).toEqual(['white']);
    expect(searchFoods(foods, 'amul').map((f) => f.id)).toEqual(['milk']);
    expect(searchFoods(foods, 'EGG WHI').map((f) => f.id)).toEqual(['white']);
    expect(searchFoods(foods, 'pizza')).toEqual([]);
  });
});

describe('library changes on their way', () => {
  const library = {
    foods: [EGG, OATS],
    presets: [
      { id: 'p1', name: 'Breakfast', sort_order: 0, items: [{ food_id: 'oats', quantity: 80, unit: 'g' }] },
      { id: 'p2', name: 'Dinner', sort_order: 1, items: [{ food_id: 'egg', quantity: 3, unit: 'piece' }] },
    ],
    targets: [{ day_type: 'rest', effective_from: '2026-11-01', targets: { kcal: 2400 } }],
    nutrients: NUTRIENTS.map((n, i) => ({ ...n, sort_order: i })),
    settings: { training_minutes: 20, reminders_on: false },
  };

  it('shows new and changed foods, favourites first', () => {
    const view = applyLibraryChanges(library, [
      { kind: 'food-save', record: MILK },
      { kind: 'food-save', record: { ...OATS, name: 'Rolled oats' } },
    ]);
    expect(view.foods.map((f) => f.name)).toEqual(['Milk, toned', 'Egg, whole', 'Rolled oats']);
    expect(library.foods).toHaveLength(2);
  });

  it('marks a deleted food in the presets that use it', () => {
    const view = applyLibraryChanges(library, [{ kind: 'food-delete', id: 'egg' }]);
    expect(view.foods.map((f) => f.id)).toEqual(['oats']);
    expect(view.presets[1].items[0].food_deleted).toBe(true);
  });

  it('reorders, replaces targets and merges settings, and doing it twice changes nothing', () => {
    const changes = [
      { kind: 'presets-order', ids: ['p2', 'p1'] },
      { kind: 'targets-save', set: { day_type: 'rest', effective_from: '2026-11-01', targets: { kcal: 2500 } } },
      { kind: 'settings-save', record: { training_minutes: 45 } },
      { kind: 'nutrient-save', record: { id: 'fibre', name: 'Fibre', unit: 'g', sort_order: 99 } },
    ];
    const once = applyLibraryChanges(library, changes);
    expect(once.presets.map((p) => p.id)).toEqual(['p2', 'p1']);
    expect(once.targets).toEqual([{ day_type: 'rest', effective_from: '2026-11-01', targets: { kcal: 2500 } }]);
    expect(once.settings).toEqual({ training_minutes: 45, reminders_on: false });
    expect(once.nutrients.at(-1).id).toBe('fibre');
    expect(applyLibraryChanges(once, changes)).toEqual(once);
  });
});

describe('making a food', () => {
  const blank = (overrides = {}) => ({ ...formFromFood(null), ...overrides });

  it('turns values per scoop into values per 100 g', () => {
    const { record } = foodFromForm(
      blank({ name: 'Whey', units: [{ name: 'scoop', amount: 32 }], valuesPer: 'scoop', defaultUnit: 'scoop', values: { kcal: 120, protein: 24 } }),
      NUTRIENTS,
    );
    expect(record.nutrients.protein).toBeCloseTo(75);
    expect(record.nutrients.kcal).toBeCloseTo(375);
    expect(record.units).toEqual({ scoop: 32 });
    expect(record.default_unit).toBe('scoop');
    expect('sodium' in record.nutrients).toBe(false);
  });

  it('says what is wrong in plain words', () => {
    expect(foodFromForm(blank({ name: ' ' }), NUTRIENTS).problem).toMatch(/name/);
    expect(foodFromForm(blank({ name: 'X', barcode: '12ab' }), NUTRIENTS).problem).toMatch(/barcode/);
    expect(foodFromForm(blank({ name: 'X', units: [{ name: 'g', amount: 1 }] }), NUTRIENTS).problem).toMatch(/built in/);
    expect(foodFromForm(blank({ name: 'X', values: { kcal: 1500 } }), NUTRIENTS).problem).toMatch(/more than 100 g can hold/);
    expect(foodFromForm(blank({ name: 'X', values: { kcal: NaN } }), NUTRIENTS).problem).toMatch(/number/);
  });

  it('starts an edit from the food, values per 100', () => {
    const form = formFromFood(EGG);
    expect(form.id).toBe('egg');
    expect(form.units).toEqual([{ name: 'piece', amount: 50 }]);
    expect(form.valuesPer).toBe('g');
    expect(form.values.protein).toBe(12.6);
    expect(formFromFood(null).id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('converts shown values between per 100 and per unit', () => {
    expect(convertValues({ kcal: 143, protein: null }, 100, 50)).toEqual({ kcal: 71.5, protein: null });
  });
});

describe('barcodes', () => {
  it('checks the last digit of food barcodes', () => {
    expect(checkDigitOk('3017620422003')).toBe(true);
    expect(checkDigitOk('3017620422004')).toBe(false);
    expect(checkDigitOk('96385074')).toBe(true);
    expect(checkDigitOk('123456')).toBe(true); // No check digit to test.
  });
});

describe('supplements', () => {
  const list = [
    { id: 'a', name: 'Omega-3', dose: '1 capsule', sort_order: 0 },
    { id: 'b', name: 'Vitamin D3', dose: null, sort_order: 1 },
  ];

  // 2026-11-19 is a Thursday; its week runs Monday 16 to Sunday 22.
  const THU = '2026-11-19';

  it('counts weeks from Monday', () => {
    expect(weekday('2026-11-16')).toBe(0);
    expect(weekday('2026-11-22')).toBe(6);
    expect(weekStart(THU)).toBe('2026-11-16');
    expect(weekStart('2026-11-16')).toBe('2026-11-16');
  });

  it('says how often in words', () => {
    expect(scheduleText(undefined)).toBe('Every day');
    expect(scheduleText({ kind: 'days', days: [0, 1, 2, 3, 4] })).toBe('Weekdays');
    expect(scheduleText({ kind: 'days', days: [5, 6] })).toBe('Weekends');
    expect(scheduleText({ kind: 'days', days: [0] })).toBe('Mondays');
    expect(scheduleText({ kind: 'days', days: [0, 2, 4] })).toBe('Mon, Wed, Fri');
    expect(scheduleText({ kind: 'weekly', times: 1 })).toBe('Once a week');
    expect(scheduleText({ kind: 'weekly', times: 3 })).toBe('3 times a week');
  });

  it('lays ticks on their way over what the server sent, for that day only', () => {
    const changes = [
      { kind: 'supplement-taken', date: THU, id: 'b', taken: true },
      { kind: 'supplement-taken', date: '2026-11-18', id: 'a', taken: true },
      { kind: 'supplement-taken', date: THU, id: 'a', taken: false },
    ];
    const day = supplementsDay(list, { [THU]: ['a'] }, changes, THU);
    expect(day.items.map((i) => [i.id, i.taken])).toEqual([['a', false], ['b', true]]);
    expect([day.done, day.due]).toEqual([1, 2]);
    expect(supplementsDay(list, {}, changes, '2026-11-18').items.find((i) => i.id === 'a').taken).toBe(true);
  });

  it('keeps a certain-days one aside on other days, unless ticked anyway', () => {
    const iron = { id: 'i', name: 'Iron', sort_order: 2, schedule: { kind: 'days', days: [0, 3] } };
    expect(supplementsDay([...list, iron], {}, [], THU).items.find((i) => i.id === 'i').note).toBe('Mon, Thu');
    const fri = supplementsDay([...list, iron], {}, [], '2026-11-20');
    expect(fri.notDue.map((i) => i.id)).toEqual(['i']);
    expect(fri.due).toBe(2);
    const ticked = supplementsDay([...list, iron], { '2026-11-20': ['i'] }, [], '2026-11-20');
    expect(ticked.items.find((i) => i.id === 'i')).toMatchObject({ taken: true, due: false });
    expect([ticked.done, ticked.due]).toEqual([0, 2]);
  });

  it('counts a few-times-a-week one across its week, then shows it done', () => {
    const fish = { id: 'f', name: 'Fish oil', sort_order: 0, schedule: { kind: 'weekly', times: 2 } };
    const week = { '2026-11-15': ['f'], '2026-11-16': ['f'] }; // Sunday before doesn't count.
    let day = supplementsDay([fish], week, [], THU);
    expect(day.items[0]).toMatchObject({ due: true, taken: false, note: '1 of 2 this week' });
    const tickTue = { kind: 'supplement-taken', date: '2026-11-17', id: 'f', taken: true };
    day = supplementsDay([fish], week, [tickTue], THU);
    expect(day.items[0]).toMatchObject({ due: false, note: 'Done this week · 2 of 2' });
    expect(day.due).toBe(0);
    day = supplementsDay([fish], week, [{ ...tickTue, date: THU }], THU);
    expect(day.items[0]).toMatchObject({ due: true, taken: true, note: '2 of 2 this week' });
  });

  it('counts only supplements still in the list, in its order', () => {
    expect(supplementsDay(list, { [THU]: ['b', 'gone', 'a'] }, [], THU).items.map((i) => i.taken)).toEqual([true, true]);
    expect(supplementsDay(undefined, undefined, [], THU)).toEqual({ items: [], notDue: [], due: 0, done: 0 });
  });

  it('adds, edits and removes them in the library, even one kept from before they existed', () => {
    const old = { foods: [], presets: [], targets: [], nutrients: [], settings: {} };
    let lib = applyLibraryChanges(old, [{ kind: 'supplement-save', record: list[1] }, { kind: 'supplement-save', record: list[0] }]);
    expect(lib.supplements.map((s) => s.name)).toEqual(['Omega-3', 'Vitamin D3']);
    lib = applyLibraryChanges(lib, [
      { kind: 'supplement-save', record: { ...list[0], dose: '2 capsules' } },
      { kind: 'supplement-delete', id: 'b' },
    ]);
    expect(lib.supplements).toEqual([{ ...list[0], dose: '2 capsules' }]);
  });
});
