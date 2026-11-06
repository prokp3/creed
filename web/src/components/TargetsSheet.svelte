<script>
  // Daily targets for training days and rest days. A change starts today: days before it keep the targets they had.
  import { untrack } from 'svelte';
  import Sheet from './Sheet.svelte';
  import { localDate, number, targetsFor } from '../lib/food.js';
  import { food as store, saveTargets } from '../lib/food.svelte.js';
  import { shortDate } from '../lib/format.js';

  let { initialType = 'training', onclose } = $props();

  const today = localDate();
  let dayType = $state(untrack(() => initialType));
  let typed = $state({});
  let saving = $state(false);

  const nutrients = $derived(store.library?.nutrients ?? []);
  const current = $derived(targetsFor(today, dayType, store.library?.targets ?? []));

  // What each box starts with: the targets in force today, or blank.
  $effect(() => {
    const values = current?.targets ?? {};
    typed = Object.fromEntries(nutrients.map((n) => [n.id, values[n.id] === undefined ? '' : String(number(values[n.id])).replaceAll(',', '')]));
  });

  const parsed = $derived(
    Object.fromEntries(
      Object.entries(typed).map(([id, text]) => {
        const value = Number(String(text).trim().replace(',', '.'));
        return [id, String(text).trim() === '' ? null : Number.isFinite(value) && value > 0 && value <= 100000 ? value : NaN];
      }),
    ),
  );
  const valid = $derived(Object.values(parsed).every((v) => v === null || Number.isFinite(v)));

  async function save() {
    if (!valid) return;
    saving = true;
    const values = Object.fromEntries(Object.entries(parsed).filter(([, v]) => v !== null));
    const ok = await saveTargets(dayType, today, values);
    saving = false;
    if (ok) onclose();
  }
</script>

<Sheet label="Targets" {onclose}>
  <div class="title-block">
    <h2 class="sheet-title">Targets</h2>
    <span class="note">From today on. Days before today keep the targets they had.</span>
  </div>

  <div class="types" role="group" aria-label="Day type">
    <button type="button" class="type pressable" aria-pressed={dayType === 'training'} onclick={() => (dayType = 'training')}>Training day</button>
    <button type="button" class="type pressable" aria-pressed={dayType === 'rest'} onclick={() => (dayType = 'rest')}>Rest day</button>
  </div>

  <div class="list">
    {#each nutrients as n (n.id)}
      <label class="list-row">
        <span class:protein={n.id === 'protein'}>{n.name}</span>
        <span class="value-input">
          <input class="field number" class:attention={Number.isNaN(parsed[n.id])} type="text" inputmode="decimal" placeholder="No target" aria-label="{n.name} target in {n.unit}" bind:value={typed[n.id]} />
          <span class="unit-label">{n.unit}</span>
        </span>
      </label>
    {/each}
  </div>
  <p class="note">
    Leave a box empty for no target. {current && current.effective_from !== today ? `These have applied since ${shortDate(current.effective_from)}.` : ''}
  </p>

  <button type="button" class="primary-button big pressable" disabled={!valid || saving} onclick={save}>
    Save {dayType === 'training' ? 'training' : 'rest'} day targets
  </button>
</Sheet>

<style>
  .title-block {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding-top: 6px;
  }

  .sheet-title {
    font: 800 26px/1.1 var(--display);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .types {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    padding: 3px;
    border-radius: 12px;
    background: var(--raised);
  }

  .type {
    height: 44px;
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--ink-2);
    font: 800 16px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .type[aria-pressed='true'] {
    background: var(--ink);
    color: var(--bg);
  }

  .value-input {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .number {
    width: 110px;
    text-align: right;
  }

  .number.attention {
    border-color: var(--attention);
  }

  .unit-label {
    width: 32px;
    font-size: 13px;
    color: var(--ink-3);
  }

  .protein {
    color: var(--protein);
  }

  .big {
    flex: none;
    height: 58px;
    border-radius: 14px;
    font-size: 20px;
  }
</style>
