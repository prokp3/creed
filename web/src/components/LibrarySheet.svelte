<script>
  // Your foods: search, add, scan, and tap one to change, copy or delete it.
  import Icon from './Icon.svelte';
  import Sheet from './Sheet.svelte';
  import { amountText, number, scale, unitAmount } from '../lib/food.js';
  import { food as store, toggleFavourite } from '../lib/food.svelte.js';

  let { onclose, onedit, oncopy, onnew, onscan } = $props();

  const SHOW_AT_MOST = 150;
  let query = $state('');

  const foods = $derived(store.library?.foods ?? []);
  const shown = $derived.by(() => {
    const q = query.trim().toLocaleLowerCase('en-IN');
    const list = q ? foods.filter((f) => `${f.name} ${f.brand ?? ''}`.toLocaleLowerCase('en-IN').includes(q)) : foods;
    return list.slice(0, SHOW_AT_MOST);
  });

  function summary(item) {
    const amount = item.default_unit === item.base ? 100 : unitAmount(item.default_unit, item.base, item.units);
    const values = scale(item.nutrients, amount);
    const per = item.default_unit === item.base ? `100 ${item.base}` : `${item.default_unit} (${number(amount)} ${item.base})`;
    const parts = [
      values.kcal === undefined ? null : `${amountText(values.kcal, 'kcal')} kcal`,
      values.protein === undefined ? null : `${amountText(values.protein, 'g')} g protein`,
    ].filter(Boolean);
    return parts.length ? `${parts.join(' · ')} per ${per}` : 'No calories or protein listed';
  }
</script>

<Sheet label="Your foods" {onclose} tall>
  <div class="title-block">
    <h2 class="sheet-title">Your foods</h2>
    <span class="note">{foods.length} foods. Starter foods have typical values; change them to match what you buy.</span>
  </div>
  <div class="actions">
    <button type="button" class="secondary-button pressable" onclick={onnew}>New food</button>
    <button type="button" class="secondary-button pressable" onclick={onscan}>Scan a barcode</button>
  </div>
  <input class="field search" type="search" placeholder="Search your foods" aria-label="Search your foods" bind:value={query} autocomplete="off" />

  {#if shown.length}
    <div class="list">
      {#each shown as item (item.id)}
        <div class="list-row food-row">
          <button type="button" class="star pressable" aria-label={item.favourite ? `Remove ${item.name} from favourites` : `Add ${item.name} to favourites`} aria-pressed={item.favourite} onclick={() => toggleFavourite(item.id)}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill={item.favourite ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2l1.1-6.2L3 9.6l6.2-.9z" /></svg>
          </button>
          <button type="button" class="food-main pressable" onclick={() => onedit(item)}>
            <span class="food-name">{item.name}</span>
            <span class="note">{item.brand ? `${item.brand} · ` : ''}{summary(item)}</span>
          </button>
          <button type="button" class="text-button copy" aria-label="Copy {item.name}" onclick={() => oncopy(item)}>Copy</button>
          <span class="chevron" aria-hidden="true"><Icon name="forward" size={16} /></span>
        </div>
      {/each}
    </div>
    {#if foods.length > shown.length && !query.trim()}<p class="note">Search to find the other {foods.length - shown.length}.</p>{/if}
  {:else}
    <p class="note">No food called “{query.trim()}”. Tap New food to add it.</p>
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

  .actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .search {
    width: 100%;
    height: 48px;
    padding: 0 14px;
    border-radius: 12px;
    background: var(--raised);
    border-color: var(--raised);
  }

  .food-row {
    gap: 4px;
    padding-left: 4px;
  }

  .star {
    display: flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: 40px;
    height: 44px;
    border: 0;
    background: transparent;
    color: var(--ink-2);
  }

  .food-main {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
    padding: 8px 0;
    border: 0;
    background: transparent;
    text-align: left;
  }

  .food-name {
    font-size: 15px;
    font-weight: 600;
  }

  .copy {
    flex: none;
    font-size: 13px;
  }

  .chevron {
    display: flex;
    color: var(--ink-3);
  }
</style>
