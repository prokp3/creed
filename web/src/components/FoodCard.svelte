<script>
  // Food on Today: calories and protein rings and your first four presets. Tap the card for the Food tab, a ring
  // for that nutrient's detail, or a preset to log it.
  import { untrack } from 'svelte';
  import FoodRing from './FoodRing.svelte';
  import Icon from './Icon.svelte';
  import { localDate } from '../lib/food.js';
  import { dayView, food as store, loadDay, loadLibrary, logPreset } from '../lib/food.svelte.js';

  let { active, freshness } = $props();

  let date = $state(localDate());
  const view = $derived(dayView(date));
  const rings = $derived(view.loaded ? view.progress.filter((p) => p.id === 'kcal' || p.id === 'protein') : []);
  const presets = $derived((store.library?.presets ?? []).slice(0, 4));

  $effect(() => {
    freshness;
    if (!active) return;
    const day = localDate();
    date = day;
    // Loading reads the store, which mustn't make this run again when the data arrives.
    untrack(() => {
      loadDay(day);
      if (!store.library) loadLibrary();
    });
  });
</script>

<section class="gutter" aria-label="Food">
  <div class="food-card">
    <a class="card-top pressable" href="#/food">
      <span class="section-heading">Food{view.loaded ? ` · ${view.dayType.type === 'training' ? 'Training day' : 'Rest day'}` : ''}</span>
      <Icon name="forward" size={18} />
    </a>
    {#if view.loaded}
      <div class="rings">
        {#each rings as item (item.id)}
          <FoodRing {item} size={118} color={item.id === 'protein' ? 'var(--protein)' : 'var(--ink)'} onclick={() => (location.hash = `#/food/${item.id}`)} />
        {/each}
      </div>
      {#if presets.length}
        <div class="presets">
          {#each presets as preset (preset.id)}
            <button type="button" class="preset pressable" onclick={() => logPreset(preset, new Date())}>{preset.name}</button>
          {/each}
        </div>
      {:else}
        <a class="secondary-button add pressable" href="#/food/add">Add food</a>
      {/if}
    {:else if view.error}
      <p class="note" role="alert">{view.error.message}</p>
    {:else}
      <p class="note" role="status">Loading…</p>
    {/if}
  </div>
</section>

<style>
  .food-card {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 12px 14px 14px;
    border-radius: 14px;
    background: var(--card);
  }

  .card-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 32px;
    color: var(--ink-3);
  }

  .rings {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .presets {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .preset {
    height: 48px;
    padding: 0 8px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: transparent;
    font: 700 16px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .add {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 48px;
    border-radius: 12px;
  }
</style>
