<script>
  // What you track: rename any nutrient, add your own (fibre, iron, caffeine…), and delete the ones you added.
  import Sheet from './Sheet.svelte';
  import { newId } from '../lib/food.js';
  import { deleteNutrient, food as store, saveNutrient } from '../lib/food.svelte.js';

  let { onclose } = $props();

  const UNITS = ['g', 'mg', 'µg', 'kcal', 'IU'];
  let names = $state({});
  let adding = $state({ name: '', unit: 'g' });
  let problem = $state('');

  const nutrients = $derived(store.library?.nutrients ?? []);

  const taken = (name, id) => nutrients.some((n) => n.id !== id && n.name.toLowerCase() === name.toLowerCase());

  function rename(n) {
    const name = (names[n.id] ?? n.name).trim();
    if (name === n.name) return;
    if (!name || name.length > 40) {
      problem = 'Names are 1 to 40 characters.';
      names[n.id] = n.name;
      return;
    }
    if (taken(name, n.id)) {
      problem = `You already have a nutrient called ${name}.`;
      names[n.id] = n.name;
      return;
    }
    problem = '';
    saveNutrient({ id: n.id, name, unit: n.unit, built_in: n.built_in, sort_order: n.sort_order });
  }

  function add() {
    const name = adding.name.trim();
    const unit = adding.unit.trim();
    if (!name || name.length > 40) {
      problem = 'Give the nutrient a name of up to 40 characters.';
      return;
    }
    if (!unit || unit.length > 12) {
      problem = 'Give it a unit, such as g or mg.';
      return;
    }
    if (taken(name, null)) {
      problem = `You already have a nutrient called ${name}.`;
      return;
    }
    problem = '';
    saveNutrient({ id: newId(), name, unit, built_in: false, sort_order: nutrients.length + 100 });
    adding = { name: '', unit: 'g' };
  }
</script>

<Sheet label="Nutrients" {onclose} tall>
  <div class="title-block">
    <h2 class="sheet-title">Nutrients</h2>
    <span class="note">Rename any of them. Ones you add appear on your foods, targets and the Food tab. A unit can't change once added.</span>
  </div>

  <div class="list">
    {#each nutrients as n (n.id)}
      <div class="list-row">
        <input class="field name" type="text" maxlength="40" aria-label="Name of {n.name}" value={names[n.id] ?? n.name} oninput={(e) => (names[n.id] = e.currentTarget.value)} onchange={() => rename(n)} />
        <span class="unit">{n.unit}</span>
        {#if n.built_in}
          <span class="tag fixed">BUILT IN</span>
        {:else}
          <button type="button" class="text-button" aria-label="Delete {n.name}" onclick={() => deleteNutrient(n)}>Delete</button>
        {/if}
      </div>
    {/each}
  </div>

  <div class="stack">
    <span class="caption">Add a nutrient</span>
    <div class="list">
      <div class="list-row">
        <input class="field name" type="text" maxlength="40" placeholder="Fibre" aria-label="New nutrient name" bind:value={adding.name} />
        <select class="field" aria-label="Unit" bind:value={adding.unit}>
          {#each UNITS as u (u)}<option value={u}>{u}</option>{/each}
        </select>
        <button type="button" class="text-button" onclick={add}>Add</button>
      </div>
    </div>
  </div>
  {#if problem}<p class="note attention" role="alert">{problem}</p>{/if}
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

  .caption {
    font: 700 13px/1 var(--display);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .name {
    flex: 1;
    min-width: 0;
  }

  .unit {
    width: 40px;
    font-size: 13px;
    color: var(--ink-3);
  }

  .fixed {
    width: 64px;
    text-align: right;
  }
</style>
