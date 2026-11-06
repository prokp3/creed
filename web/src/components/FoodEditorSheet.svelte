<script>
  // Making or changing a food: its name, how it's measured, its units (a 50 g piece, a 30 g scoop), and its values,
  // typed per 100 g (or ml) or per unit, as the label gives them. Blank values are unknown, not zero.
  import { untrack } from 'svelte';
  import Icon from './Icon.svelte';
  import Sheet from './Sheet.svelte';
  import { convertValues, foodFromForm, formFromFood, newId, number } from '../lib/food.js';
  import { deleteFood, food as store, saveFood } from '../lib/food.svelte.js';

  // `food`: the food to change, a scanned draft, or null for a new one. `copy` makes a new food from it.
  let { food = null, copy = false, note = '', onclose, onsaved, onback = null } = $props();

  const isNew = untrack(() => !food?.id || copy);
  let form = $state(
    untrack(() => {
      const start = formFromFood(food);
      if (copy) return { ...start, id: newId(), name: `${start.name} (copy)`.slice(0, 80), barcode: '', source: 'manual' };
      return start;
    }),
  );
  let typed = $state(untrack(() => Object.fromEntries(Object.entries(form.values).map(([k, v]) => [k, String(v)]))));
  let newUnit = $state({ name: '', amount: '' });
  let problem = $state('');
  let confirmDelete = $state(false);

  const nutrients = $derived(store.library?.nutrients ?? []);
  const perOptions = $derived([form.base, ...form.units.filter((u) => u.name.trim() && u.amount > 0).map((u) => u.name.trim())]);
  const unitOptions = $derived(perOptions);
  const amountOf = (unit) => (unit === form.base ? 100 : form.units.find((u) => u.name.trim() === unit)?.amount);

  function readNumber(text) {
    const cleaned = String(text ?? '').trim().replace(',', '.');
    if (!cleaned) return null;
    const value = Number(cleaned);
    return Number.isFinite(value) ? value : NaN;
  }

  function setPer(next) {
    if (next === form.valuesPer) return;
    const from = amountOf(form.valuesPer);
    const to = amountOf(next);
    const values = {};
    for (const [k, v] of Object.entries(typed)) values[k] = readNumber(v);
    const converted = convertValues(values, from, to);
    typed = Object.fromEntries(Object.entries(converted).map(([k, v]) => [k, v === null || Number.isNaN(v) ? typed[k] ?? '' : String(v)]));
    form.valuesPer = next;
  }

  function addUnit() {
    const name = newUnit.name.trim();
    const amount = readNumber(newUnit.amount);
    if (!name || !(amount > 0)) {
      problem = `Give the unit a name and how many ${form.base} one is.`;
      return;
    }
    if (form.units.some((u) => u.name.trim() === name)) {
      problem = `There's already a unit called ${name}.`;
      return;
    }
    form.units = [...form.units, { name, amount }];
    newUnit = { name: '', amount: '' };
    problem = '';
  }

  function removeUnit(name) {
    if (form.valuesPer === name) setPer(form.base);
    form.units = form.units.filter((u) => u.name !== name);
    if (form.defaultUnit === name) form.defaultUnit = form.base;
  }

  function save() {
    const values = {};
    for (const [k, v] of Object.entries(typed)) values[k] = readNumber(v);
    const result = foodFromForm({ ...$state.snapshot(form), values }, nutrients);
    if (result.problem) {
      problem = result.problem;
      return;
    }
    if (result.record.barcode) {
      const clash = (store.library?.foods ?? []).find((f) => f.barcode === result.record.barcode && f.id !== result.record.id);
      if (clash) {
        problem = `${clash.name} already has this barcode.`;
        return;
      }
    }
    saveFood(result.record, isNew ? `${result.record.name} added to your foods` : `${result.record.name} saved`);
    onsaved?.(result.record);
  }

  function remove() {
    if (!confirmDelete) {
      confirmDelete = true;
      return;
    }
    deleteFood(food);
    onclose();
  }

  const unitLabel = (u) => (u === form.base ? `100 ${form.base}` : `1 ${u} (${number(amountOf(u))} ${form.base})`);
</script>

<Sheet label={isNew ? 'New food' : `Edit ${food.name}`} {onclose} tall>
  <div class="head">
    {#if onback}
      <button type="button" class="icon-button pressable" aria-label="Back" onclick={onback}><Icon name="back" size={22} stroke={2.4} /></button>
    {/if}
    <div class="title-block">
      <h2 class="sheet-title">{isNew ? (copy ? 'Copy food' : 'New food') : 'Edit food'}</h2>
      {#if note}<span class="note">{note}</span>{/if}
    </div>
  </div>

  <div class="list">
    <label class="list-row"><span>Name</span><input class="field wide" type="text" maxlength="80" bind:value={form.name} placeholder="Greek yogurt" /></label>
    <label class="list-row"><span>Brand</span><input class="field wide" type="text" maxlength="80" bind:value={form.brand} placeholder="Optional" /></label>
    <label class="list-row"><span>Barcode</span><input class="field wide" type="text" inputmode="numeric" maxlength="14" bind:value={form.barcode} placeholder="Optional" /></label>
  </div>

  <div class="stack">
    <span class="caption">Measured in</span>
    <div class="segments" role="group" aria-label="Measured in">
      <button type="button" class="segment-button pressable" aria-pressed={form.base === 'g'} onclick={() => { form.base = 'g'; if (form.valuesPer === 'ml') form.valuesPer = 'g'; if (form.defaultUnit === 'ml') form.defaultUnit = 'g'; }}>Grams</button>
      <button type="button" class="segment-button pressable" aria-pressed={form.base === 'ml'} onclick={() => { form.base = 'ml'; if (form.valuesPer === 'g') form.valuesPer = 'ml'; if (form.defaultUnit === 'g') form.defaultUnit = 'ml'; }}>Millilitres</button>
    </div>
  </div>

  <div class="stack">
    <span class="caption">Units</span>
    <div class="list">
      {#each form.units as unit (unit.name)}
        <div class="list-row">
          <span>1 {unit.name} = {number(unit.amount)} {form.base}</span>
          <button type="button" class="text-button" aria-label="Remove {unit.name}" onclick={() => removeUnit(unit.name)}>Remove</button>
        </div>
      {/each}
      <div class="list-row add-unit">
        <input class="field" type="text" maxlength="20" placeholder="piece" aria-label="New unit name" bind:value={newUnit.name} />
        <span class="equals">=</span>
        <input class="field small" type="text" inputmode="decimal" placeholder="50" aria-label="How many {form.base} one is" bind:value={newUnit.amount} />
        <span class="unit-label">{form.base}</span>
        <button type="button" class="text-button" onclick={addUnit}>Add</button>
      </div>
    </div>
    {#if unitOptions.length > 1}
      <label class="list-row plain">
        <span>Usually logged in</span>
        <select class="field" bind:value={form.defaultUnit}>
          {#each unitOptions as u (u)}<option value={u}>{u}</option>{/each}
        </select>
      </label>
    {/if}
  </div>

  <div class="stack">
    <span class="caption">Values for</span>
    {#if perOptions.length > 1}
      <div class="segments wrap" role="group" aria-label="Values for">
        {#each perOptions as u (u)}
          <button type="button" class="segment-button pressable" aria-pressed={form.valuesPer === u} onclick={() => setPer(u)}>{unitLabel(u)}</button>
        {/each}
      </div>
    {:else}
      <span class="note">Per 100 {form.base}. Add a unit above to type values per serving instead.</span>
    {/if}
    <div class="list">
      {#each nutrients as n (n.id)}
        <label class="list-row">
          <span class:protein={n.id === 'protein'}>{n.name}</span>
          <span class="value-input">
            <input class="field number" type="text" inputmode="decimal" placeholder="—" aria-label="{n.name} in {n.unit}" bind:value={typed[n.id]} />
            <span class="unit-label">{n.unit}</span>
          </span>
        </label>
      {/each}
    </div>
    <p class="note">Leave a value blank if the label doesn't give it. Blank means unknown, not zero.</p>
  </div>

  <label class="stack">
    <span class="caption">Notes</span>
    <input class="field" type="text" maxlength="500" placeholder="Optional" bind:value={form.notes} />
  </label>

  <label class="list-row plain">
    <span>Favourite</span>
    <input type="checkbox" class="check" bind:checked={form.favourite} />
  </label>

  {#if problem}<p class="note attention" role="alert">{problem}</p>{/if}

  <button type="button" class="primary-button big pressable" onclick={save}>{isNew ? 'Add to your foods' : 'Save'}</button>
  {#if !isNew}
    <button type="button" class="text-button grey" onclick={remove}>{confirmDelete ? `Tap again to delete ${food.name}` : 'Delete this food'}</button>
    {#if confirmDelete}<p class="note">Meals already logged keep their own copy. Presets that use it will skip it.</p>{/if}
  {/if}
</Sheet>

<style>
  .head {
    display: flex;
    align-items: flex-start;
    gap: 6px;
  }

  .title-block {
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1;
    min-width: 0;
    padding-top: 6px;
  }

  .sheet-title {
    font: 800 26px/1.1 var(--display);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .icon-button {
    display: flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: 44px;
    height: 44px;
    margin-left: -10px;
    border: 0;
    background: transparent;
    color: var(--ink);
  }

  .caption {
    font: 700 13px/1 var(--display);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .wide {
    flex: 1;
    min-width: 0;
    max-width: 220px;
  }

  .segments {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(0, 1fr);
    padding: 3px;
    border-radius: 12px;
    background: var(--raised);
  }

  .segments.wrap {
    grid-auto-flow: row;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 3px;
  }

  .segment-button {
    min-height: 44px;
    padding: 4px 6px;
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--ink-2);
    font: 800 15px/1.1 var(--display);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .segment-button[aria-pressed='true'] {
    background: var(--ink);
    color: var(--bg);
  }

  .add-unit {
    gap: 6px;
  }

  .add-unit .field:first-child {
    flex: 1;
    min-width: 0;
  }

  .small {
    width: 64px;
    text-align: right;
  }

  .equals {
    color: var(--ink-3);
  }

  .plain {
    padding: 0;
  }

  .value-input {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .number {
    width: 96px;
    text-align: right;
  }

  .unit-label {
    width: 32px;
    font-size: 13px;
    color: var(--ink-3);
  }

  .protein {
    color: var(--protein);
  }

  .check {
    width: 24px;
    height: 24px;
    accent-color: var(--ink);
  }

  .big {
    flex: none;
    height: 58px;
    border-radius: 14px;
    font-size: 20px;
  }

  .grey {
    align-self: center;
  }
</style>
