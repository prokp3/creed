<script>
  // One meal: what was in it, changing an amount or the time, deleting, and saving it as a preset to log in one tap.
  import { untrack } from 'svelte';
  import Icon from './Icon.svelte';
  import QuantityPanel from './QuantityPanel.svelte';
  import Sheet from './Sheet.svelte';
  import TimePicker from './TimePicker.svelte';
  import { amountText, atTime, clockText, entryNutrients, isOneOff, presetFromMeal, quantityText, withQuantity } from '../lib/food.js';
  import { deleteEntries, food as store, savePreset, updateEntries } from '../lib/food.svelte.js';

  let { meal, nutrients, onclose } = $props();

  let editingId = $state(null);
  let quantity = $state(1);
  let unit = $state('g');
  // Starting values only: the meal can change under the sheet while it's open.
  let when = $state(untrack(() => new Date(meal.logged_at)));
  let naming = $state(false);
  let presetName = $state(untrack(() => (meal.label && meal.label !== 'Quick add' ? meal.label : '')));

  const editing = $derived(meal.entries.find((e) => e.id === editingId) ?? null);
  const timeChanged = $derived(when.getTime() !== new Date(meal.logged_at).getTime());
  const foodsById = $derived(new Map((store.library?.foods ?? []).map((f) => [f.id, f])));
  const canPreset = $derived(meal.entries.some((e) => e.food_id && foodsById.has(e.food_id)));
  const quantityValid = $derived(Number.isFinite(quantity) && quantity > 0 && quantity <= 100000);
  const kcal = (values) => (values.kcal === undefined ? '—' : `${amountText(values.kcal, 'kcal')} kcal`);
  const protein = (values) => (values.protein === undefined ? '' : `${amountText(values.protein, 'g')} g protein`);

  function edit(entry) {
    editingId = entry.id;
    quantity = entry.quantity;
    unit = entry.unit;
  }

  function saveEdit() {
    if (!editing || !quantityValid) return;
    updateEntries([editing], [withQuantity(editing, quantity, unit)]);
    editingId = null;
  }

  function deleteOne(entry) {
    editingId = null;
    deleteEntries([entry], `${entry.food_name} deleted`);
    if (meal.entries.length === 1) onclose();
  }

  function deleteMeal() {
    deleteEntries(meal.entries, `${meal.label} deleted · ${meal.entries.length} ${meal.entries.length === 1 ? 'item' : 'items'}`);
    onclose();
  }

  function saveTime() {
    // Every entry moves by the same amount, so a meal keeps its shape.
    const shift = when.getTime() - new Date(meal.logged_at).getTime();
    const moved = meal.entries.map((e) => atTime(e, new Date(new Date(e.logged_at).getTime() + shift)));
    updateEntries(meal.entries, moved);
  }

  async function makePreset() {
    const name = presetName.trim().slice(0, 40);
    if (!name) return;
    const { left_out, ...preset } = presetFromMeal(meal, name, foodsById);
    naming = false;
    await savePreset(preset);
  }

  const unitOptionsFor = (entry) => [...new Set([entry.unit, ...Object.keys(entry.unit_amounts ?? {}), ...(isOneOff(entry) ? [] : [entry.base])])];
</script>

<Sheet label={meal.label} {onclose}>
  {#if editing}
    <div class="head">
      <button type="button" class="icon-button pressable" aria-label="Back to the meal" onclick={() => (editingId = null)}><Icon name="back" size={22} stroke={2.4} /></button>
      <div class="title-block">
        <h2 class="sheet-title">{editing.food_name}</h2>
        <span class="note">The values saved when you logged it. Editing the food later doesn't change this.</span>
      </div>
    </div>
    <QuantityPanel base={editing.base} units={editing.unit_amounts} unitOptions={unitOptionsFor(editing)} per100={editing.nutrients_per_100} {nutrients} bind:quantity bind:unit />
    <button type="button" class="primary-button big pressable" disabled={!quantityValid} onclick={saveEdit}>Save</button>
    <button type="button" class="text-button danger" onclick={() => deleteOne(editing)}>Delete {editing.food_name}</button>
  {:else}
    <div class="title-block">
      <h2 class="sheet-title">{meal.label}</h2>
      <span class="totals">
        <span>{kcal(meal.totals)}</span>
        {#if meal.totals.protein !== undefined}<span class="protein">{protein(meal.totals)}</span>{/if}
      </span>
    </div>

    <div class="list">
      {#each meal.entries as entry (entry.id)}
        {@const values = entryNutrients(entry)}
        <button type="button" class="list-row entry pressable" onclick={() => edit(entry)}>
          <span class="entry-text">
            <span class="entry-name">{entry.food_name}</span>
            <span class="note">{isOneOff(entry) ? (entry.quantity === 1 ? 'Quick add' : `${entry.quantity} × quick add`) : quantityText(entry.quantity, entry.unit)}</span>
          </span>
          <span class="entry-values">
            <span>{kcal(values)}</span>
            {#if values.protein !== undefined}<span class="protein small">{protein(values)}</span>{/if}
          </span>
        </button>
      {/each}
    </div>

    <div class="time-row">
      <span class="caption">Time</span>
      <TimePicker bind:value={when} />
    </div>
    {#if timeChanged}
      <button type="button" class="secondary-button pressable" onclick={saveTime}>Move to {clockText(when)}</button>
    {/if}

    {#if naming}
      <div class="stack">
        <label class="stack">
          <span class="caption">Preset name</span>
          <input class="field" type="text" maxlength="40" placeholder="Post-ride" bind:value={presetName} />
        </label>
        <button type="button" class="primary-button pressable" disabled={!presetName.trim()} onclick={makePreset}>Save preset</button>
        {#if meal.entries.some((e) => !e.food_id || !foodsById.has(e.food_id))}
          <p class="note">Quick adds and deleted foods aren't in your library, so they're left out of the preset.</p>
        {/if}
      </div>
    {:else if canPreset}
      <button type="button" class="secondary-button pressable" onclick={() => (naming = true)}>Save as a preset</button>
    {/if}

    <button type="button" class="text-button danger" onclick={deleteMeal}>Delete {meal.entries.length === 1 ? 'this' : 'this meal'}</button>
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

  .totals {
    display: flex;
    gap: 12px;
    font: 800 18px/1.2 var(--display);
  }

  .entry {
    width: 100%;
    border: 0;
    background: transparent;
    text-align: left;
  }

  .list .entry + .entry {
    border-top: 1px solid var(--line);
  }

  .entry-text,
  .entry-values {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding: 6px 0;
  }

  .entry-values {
    align-items: flex-end;
    flex: none;
    font: 800 17px/1.1 var(--display);
  }

  .entry-name {
    font-size: 15px;
    font-weight: 600;
  }

  .small {
    font: 500 12px/1.2 var(--body);
  }

  .protein {
    color: var(--protein);
  }

  .caption {
    font: 700 13px/1 var(--display);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .time-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    min-height: 44px;
  }

  .big {
    flex: none;
    height: 58px;
    border-radius: 14px;
    font-size: 20px;
  }

  /* Red means a problem in this app, so deleting stays grey. */
  .danger {
    align-self: center;
    color: var(--ink-2);
  }
</style>
