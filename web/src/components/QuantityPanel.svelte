<script>
  // How much of one food: big − and + buttons, the number itself, the unit, and what that amount holds.
  // Used for logging a food and for changing an entry already logged.
  import { amountText, baseAmount, convertQuantity, number, scale, startingQuantity, stepQuantity } from '../lib/food.js';

  let {
    base,
    units = {},
    unitOptions,
    per100,
    nutrients,
    quantity = $bindable(),
    unit = $bindable(),
    // When given, a food with no unit for how you eat it can get one here: (name, amount of the base) => void.
    onaddunit = null,
  } = $props();

  // Common ways food is measured. Each still needs its weight, since a katori of rice and of dal differ.
  const SUGGESTED = ['piece', 'katori', 'bowl', 'cup', 'plate', 'slice', 'tbsp', 'tsp', 'scoop', 'glass', 'serving', 'handful'];
  let adding = $state(false);
  let newName = $state('');
  let newAmount = $state('');
  let addProblem = $state('');

  let typed = $state(String(number(quantity)).replaceAll(',', ''));

  // A unit just added reaches `units` a moment after `unit`, so an unknown unit reads as no amount yet.
  const amount = $derived.by(() => {
    if (!(Number.isFinite(quantity) && quantity > 0)) return null;
    try {
      return baseAmount(quantity, unit, base, units);
    } catch {
      return null;
    }
  });
  const values = $derived(amount === null ? {} : scale(per100, amount));
  const MAIN = ['kcal', 'protein', 'carbs', 'fat', 'sodium'];
  const nutrientById = $derived(new Map(nutrients.map((n) => [n.id, n])));
  const others = $derived(nutrients.filter((n) => !MAIN.includes(n.id)));

  function setQuantity(next) {
    quantity = next;
    typed = String(number(next)).replaceAll(',', '');
  }

  function step(direction) {
    setQuantity(stepQuantity(Number.isFinite(quantity) ? quantity : 0, unit, base, direction));
  }

  function oninput(event) {
    typed = event.currentTarget.value;
    const parsed = Number(typed.replace(',', '.'));
    quantity = typed.trim() && Number.isFinite(parsed) ? parsed : NaN;
  }

  function chooseUnit(next) {
    if (next === unit) return;
    // Keep about the same amount of food when switching between a unit and grams.
    const valid = amount !== null;
    const before = unit;
    unit = next;
    setQuantity(valid ? convertQuantity(quantity, before, next, base, units) : startingQuantity(next, base));
  }

  function addUnit() {
    const name = newName.trim();
    const grams = Number(String(newAmount).trim().replace(',', '.'));
    if (!name || name.length > 20) {
      addProblem = 'Give the unit a name of up to 20 characters.';
      return;
    }
    if (name === 'g' || name === 'ml' || unitOptions.includes(name)) {
      addProblem = `This food can already be measured in ${name}.`;
      return;
    }
    if (!(grams > 0) || grams > 100000) {
      addProblem = `Say how many ${base} one ${name} is.`;
      return;
    }
    onaddunit(name, grams);
    unit = name;
    setQuantity(1);
    adding = false;
    newName = '';
    newAmount = '';
    addProblem = '';
  }

  const unitLabel = (u) => (u === base ? (base === 'g' ? 'Grams' : 'ml') : `${u} · ${number(units[u])} ${base}`);
  const show = (id) => {
    const n = nutrientById.get(id);
    if (!n) return null;
    const value = values[id];
    return { name: n.name, text: value === undefined ? 'Not listed' : `${amountText(value, n.unit)}${n.unit === 'kcal' ? '' : ` ${n.unit}`}` };
  };
</script>

<div class="stepper">
  <button type="button" class="round pressable" aria-label="Less" onclick={() => step(-1)}>
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14" /></svg>
  </button>
  <label class="number">
    <span class="caption">Quantity</span>
    <input type="text" inputmode="decimal" value={typed} {oninput} aria-label="Quantity" />
  </label>
  <button type="button" class="round pressable" aria-label="More" onclick={() => step(1)}>
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
  </button>
</div>

{#if unitOptions.length > 1 || onaddunit}
  <div class="units" class:wrap={unitOptions.length + (onaddunit ? 1 : 0) > 2} role="group" aria-label="Unit">
    {#each unitOptions as option (option)}
      <button type="button" class="unit pressable" aria-pressed={option === unit} onclick={() => chooseUnit(option)}>{unitLabel(option)}</button>
    {/each}
    {#if onaddunit}
      <button type="button" class="unit add-unit pressable" aria-expanded={adding} onclick={() => (adding = !adding)}>+ Add a unit</button>
    {/if}
  </div>
{/if}

{#if adding}
  <div class="new-unit">
    <div class="suggestions" role="group" aria-label="Common units">
      {#each SUGGESTED.filter((u) => !unitOptions.includes(u)) as u (u)}
        <button type="button" class="suggestion pressable" aria-pressed={newName === u} onclick={() => (newName = u)}>{u}</button>
      {/each}
    </div>
    <div class="new-row">
      <input class="field name" type="text" maxlength="20" placeholder="Unit, such as piece" aria-label="Unit name" bind:value={newName} />
      <span class="equals">=</span>
      <input class="field amount" type="text" inputmode="decimal" placeholder="50" aria-label="How many {base} one is" bind:value={newAmount} />
      <span class="base">{base}</span>
    </div>
    <p class="note">Weigh one if you can. It's saved to this food, so it's there next time.</p>
    {#if addProblem}<p class="note attention" role="alert">{addProblem}</p>{/if}
    <button type="button" class="secondary-button pressable" onclick={addUnit}>Add {newName.trim() || 'unit'}</button>
  </div>
{/if}

<div class="values" aria-live="polite">
  {#each [show('kcal'), show('protein')] as cell, i (i)}
    {#if cell}
      <span class="cell" class:protein={i === 1}>
        <span class="caption">{i === 0 ? 'Calories' : cell.name}</span>
        <span class="big">{cell.text}</span>
      </span>
    {/if}
  {/each}
  <span class="cell">
    <span class="caption">Amount</span>
    <span class="big">{amount === null ? '—' : `${amountText(amount, base === 'g' ? 'g' : 'ml')} ${base}`}</span>
  </span>
  {#each ['carbs', 'fat', 'sodium'] as id (id)}
    {@const cell = show(id)}
    {#if cell}
      <span class="cell"><span class="caption">{cell.name}</span><span class="small">{cell.text}</span></span>
    {/if}
  {/each}
  {#each others as n (n.id)}
    {@const cell = show(n.id)}
    <span class="cell"><span class="caption">{cell.name}</span><span class="small">{cell.text}</span></span>
  {/each}
</div>

<style>
  .stepper {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .round {
    display: flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: 64px;
    height: 64px;
    border: 1px solid var(--border);
    border-radius: 32px;
    background: transparent;
    color: var(--ink);
  }

  .number {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    flex: 1;
    min-width: 0;
  }

  .number input {
    width: 100%;
    max-width: 160px;
    border: 0;
    background: transparent;
    color: var(--ink);
    text-align: center;
    font: 800 64px/1 var(--display);
  }

  .caption {
    font: 700 12px/1 var(--display);
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .units {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(0, 1fr);
    padding: 3px;
    border-radius: 12px;
    background: var(--raised);
  }

  .units.wrap {
    grid-auto-flow: row;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 3px;
  }

  .unit {
    height: 44px;
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--ink-2);
    font: 800 16px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .unit[aria-pressed='true'] {
    background: var(--ink);
    color: var(--bg);
  }

  .add-unit {
    color: var(--ink);
  }

  .new-unit {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    border-radius: 14px;
    background: var(--card);
  }

  .suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .suggestion {
    min-height: 36px;
    padding: 0 12px;
    border: 1px solid var(--border);
    border-radius: 18px;
    background: transparent;
    color: var(--ink-2);
    font: 600 14px/1 var(--body);
  }

  .suggestion[aria-pressed='true'] {
    border-color: var(--ink);
    background: var(--ink);
    color: var(--bg);
  }

  .new-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .new-row .name {
    flex: 1;
    min-width: 0;
  }

  .new-row .amount {
    width: 72px;
    text-align: right;
  }

  .equals,
  .base {
    font-size: 13px;
    color: var(--ink-3);
  }

  .values {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px 8px;
    padding: 14px;
    border-radius: 14px;
    background: var(--card);
  }

  .cell {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .big {
    font: 800 24px/1 var(--display);
  }

  .small {
    font: 800 18px/1 var(--display);
  }

  .protein .caption,
  .protein .big {
    color: var(--protein);
  }
</style>
