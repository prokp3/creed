<script>
  // Your presets: reorder and delete. New ones are saved from a logged meal.
  import Icon from './Icon.svelte';
  import Sheet from './Sheet.svelte';
  import { quantityText } from '../lib/food.js';
  import { deletePreset, food as store, movePreset } from '../lib/food.svelte.js';

  let { onclose } = $props();

  const presets = $derived(store.library?.presets ?? []);
  const summary = (preset) =>
    preset.items.map((i) => `${i.food_name}${i.food_deleted ? ' (deleted)' : ''}, ${quantityText(i.quantity, i.unit)}`).join(' · ');
</script>

<Sheet label="Presets" {onclose}>
  <div class="title-block">
    <h2 class="sheet-title">Presets</h2>
    <span class="note">To make one, log a meal, tap it, and choose Save as a preset.</span>
  </div>
  {#if presets.length}
    <div class="list">
      {#each presets as preset, i (preset.id)}
        <div class="list-row">
          <span class="preset-text">
            <span class="preset-name">{preset.name}</span>
            <span class="note">{summary(preset)}</span>
          </span>
          <span class="actions">
            <button type="button" class="icon-button pressable" aria-label="Move {preset.name} up" disabled={i === 0} onclick={() => movePreset(preset, -1)}><span class="up"><Icon name="down" size={18} /></span></button>
            <button type="button" class="icon-button pressable" aria-label="Move {preset.name} down" disabled={i === presets.length - 1} onclick={() => movePreset(preset, 1)}><Icon name="down" size={18} /></button>
            <button type="button" class="text-button" aria-label="Delete {preset.name}" onclick={() => deletePreset(preset)}>Delete</button>
          </span>
        </div>
      {/each}
    </div>
  {:else}
    <p class="note">No presets yet.</p>
  {/if}
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

  .preset-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding: 8px 0;
  }

  .preset-name {
    font: 700 17px/1.1 var(--display);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .actions {
    display: flex;
    align-items: center;
    flex: none;
  }

  .icon-button {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 44px;
    border: 0;
    background: transparent;
    color: var(--ink-2);
  }

  .icon-button:disabled {
    opacity: 0.3;
  }

  .up {
    display: flex;
    transform: rotate(180deg);
  }
</style>
