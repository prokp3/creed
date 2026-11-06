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
  } = $props();

  let typed = $state(String(number(quantity)).replaceAll(',', ''));

  const amount = $derived(Number.isFinite(quantity) && quantity > 0 ? baseAmount(quantity, unit, base, units) : null);
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

{#if unitOptions.length > 1}
  <div class="units" class:wrap={unitOptions.length > 2} role="group" aria-label="Unit">
    {#each unitOptions as option (option)}
      <button type="button" class="unit pressable" aria-pressed={option === unit} onclick={() => chooseUnit(option)}>{unitLabel(option)}</button>
    {/each}
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
