<script>
  // Making or changing a preset: a name and the foods it logs, each with an amount. One tap logs them all.
  import { untrack } from 'svelte';
  import Icon from './Icon.svelte';
  import Sheet from './Sheet.svelte';
  import { amountText, baseAmount, newId, scale, searchFoods, startingQuantity, unitChoices } from '../lib/food.js';
  import { food as store, savePreset } from '../lib/food.svelte.js';

  // `preset`: the one to change, or null for a new one. `copy` makes a new preset from it.
  let { preset = null, copy = false, onclose, onback = null } = $props();

  const isNew = untrack(() => !preset || copy);
  let name = $state(untrack(() => (preset ? (copy ? `${preset.name} (copy)`.slice(0, 40) : preset.name) : '')));
  let items = $state(
    untrack(() =>
      (preset?.items ?? []).filter((i) => !i.food_deleted).map((i) => ({ food_id: i.food_id, quantity: String(i.quantity), unit: i.unit })),
    ),
  );
  let picking = $state(untrack(() => !preset));
  let query = $state('');
  let problem = $state('');

  const foods = $derived(store.library?.foods ?? []);
  const byId = $derived(new Map(foods.map((f) => [f.id, f])));
  const matches = $derived(
    query.trim() ? searchFoods(foods, query) : [...searchFoods(foods, '', store.library?.recent_food_ids ?? []), ...foods].filter((f, i, all) => all.findIndex((g) => g.id === f.id) === i),
  );
  const dropped = $derived((preset?.items ?? []).filter((i) => i.food_deleted).length);

  const quantityOf = (item) => Number(String(item.quantity).replace(',', '.'));

  const totals = $derived.by(() => {
    const sum = {};
    for (const item of items) {
      const f = byId.get(item.food_id);
      const q = quantityOf(item);
      if (!f || !(q > 0)) continue;
      for (const [k, v] of Object.entries(scale(f.nutrients, baseAmount(q, item.unit, f.base, f.units)))) sum[k] = (sum[k] ?? 0) + v;
    }
    return sum;
  });

  function addFood(f) {
    items = [...items, { food_id: f.id, quantity: String(startingQuantity(f.default_unit, f.base)), unit: f.default_unit }];
    picking = false;
    query = '';
  }

  function move(index, direction) {
    const next = [...items];
    const to = index + direction;
    if (to < 0 || to >= next.length) return;
    [next[index], next[to]] = [next[to], next[index]];
    items = next;
  }

  function save() {
    const clean = name.trim();
    if (!clean || clean.length > 40) {
      problem = 'Give the preset a name of up to 40 characters.';
      return;
    }
    if (!items.length) {
      problem = 'Add at least one food.';
      return;
    }
    if (items.length > 50) {
      problem = 'A preset can have up to 50 foods.';
      return;
    }
    for (const item of items) {
      const q = quantityOf(item);
      if (!(q > 0) || q > 100000) {
        problem = `Check the amount of ${byId.get(item.food_id)?.name ?? 'each food'}.`;
        return;
      }
    }
    const record = {
      id: isNew ? newId() : preset.id,
      name: clean,
      items: items.map((i) => ({ food_id: i.food_id, quantity: quantityOf(i), unit: i.unit })),
    };
    if (!isNew) record.sort_order = preset.sort_order;
    savePreset(record);
    onback ? onback() : onclose();
  }
</script>

<Sheet label={isNew ? 'New preset' : `Edit ${preset.name}`} {onclose} tall>
  <div class="head">
    {#if onback}
      <button type="button" class="icon-button pressable" aria-label="Back" onclick={onback}><Icon name="back" size={22} stroke={2.4} /></button>
    {/if}
    <div class="title-block">
      <h2 class="sheet-title">{isNew ? 'New preset' : 'Edit preset'}</h2>
      <span class="note">One tap on it logs all of these at once.</span>
    </div>
  </div>

  <label class="stack">
    <span class="caption">Name</span>
    <input class="field" type="text" maxlength="40" placeholder="Post-ride" bind:value={name} />
  </label>

  <div class="stack">
    <span class="caption">Foods</span>
    {#if items.length}
      <div class="list">
        {#each items as item, i (i)}
          {@const f = byId.get(item.food_id)}
          <div class="list-block item">
            <div class="list-inner">
              <span class="item-name">{f?.name ?? 'A food no longer in your library'}</span>
              <span class="item-actions">
                <button type="button" class="icon-small pressable" aria-label="Move up" disabled={i === 0} onclick={() => move(i, -1)}><span class="up"><Icon name="down" size={16} /></span></button>
                <button type="button" class="icon-small pressable" aria-label="Move down" disabled={i === items.length - 1} onclick={() => move(i, 1)}><Icon name="down" size={16} /></button>
                <button type="button" class="text-button" aria-label="Remove {f?.name ?? 'food'}" onclick={() => (items = items.filter((_, j) => j !== i))}>Remove</button>
              </span>
            </div>
            {#if f}
              <div class="amount">
                <input class="field number" type="text" inputmode="decimal" aria-label="Amount of {f.name}" bind:value={item.quantity} />
                <select class="field" aria-label="Unit for {f.name}" bind:value={item.unit}>
                  {#each unitChoices(f) as u (u)}<option value={u}>{u}</option>{/each}
                </select>
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {:else}
      <p class="note">No foods yet.</p>
    {/if}
    {#if dropped}<p class="note">{dropped} deleted {dropped === 1 ? 'food was' : 'foods were'} taken out.</p>{/if}
  </div>

  {#if picking}
    <div class="stack">
      <input class="field search" type="search" placeholder="Search your foods" aria-label="Search your foods" bind:value={query} autocomplete="off" />
      <div class="list">
        {#each matches.slice(0, 40) as f (f.id)}
          <button type="button" class="list-row pick pressable" onclick={() => addFood(f)}>
            <span>{f.name}{f.brand ? ` · ${f.brand}` : ''}</span>
            <span class="note">Add</span>
          </button>
        {/each}
      </div>
    </div>
  {:else}
    <button type="button" class="secondary-button pressable" onclick={() => (picking = true)}>Add a food</button>
  {/if}

  {#if items.length}
    <p class="note totals">
      All together: {totals.kcal === undefined ? 'kcal not listed' : `${amountText(totals.kcal, 'kcal')} kcal`}{totals.protein === undefined ? '' : ` · ${amountText(totals.protein, 'g')} g protein`}
    </p>
  {/if}
  {#if problem}<p class="note attention" role="alert">{problem}</p>{/if}
  <button type="button" class="primary-button big pressable" onclick={save}>{isNew ? 'Save preset' : 'Save'}</button>
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

  .item-name {
    font-size: 15px;
    font-weight: 600;
  }

  .item-actions {
    display: flex;
    align-items: center;
    flex: none;
  }

  .icon-small {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 44px;
    border: 0;
    background: transparent;
    color: var(--ink-2);
  }

  .icon-small:disabled {
    opacity: 0.3;
  }

  .up {
    display: flex;
    transform: rotate(180deg);
  }

  .amount {
    display: flex;
    gap: 8px;
  }

  .number {
    width: 96px;
    text-align: right;
  }

  .search {
    width: 100%;
    height: 48px;
    padding: 0 14px;
    border-radius: 12px;
    background: var(--raised);
    border-color: var(--raised);
  }

  .pick {
    width: 100%;
    border: 0;
    background: transparent;
    text-align: left;
  }

  .list .pick + .pick {
    border-top: 1px solid var(--line);
  }

  .totals {
    color: var(--ink);
  }

  .big {
    flex: none;
    height: 58px;
    border-radius: 14px;
    font-size: 20px;
  }
</style>
