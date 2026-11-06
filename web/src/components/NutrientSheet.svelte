<script>
  // One nutrient for the day: eaten, target, what's left, and which foods gave it.
  import Sheet from './Sheet.svelte';
  import { amountText, contributions, quantityText, isOneOff } from '../lib/food.js';

  let { item, entries, color = 'var(--ink)', onclose, onsettargets } = $props();

  const rows = $derived(contributions(entries, item.id));
  const unit = $derived(item.unit === 'kcal' ? 'kcal' : item.unit);
  const show = (value) => `${amountText(value, item.unit)} ${unit}`;
  const missing = $derived(entries.filter((e) => !(item.id in e.nutrients_per_100)));
</script>

<Sheet label={item.name} {onclose}>
  <h2 class="sheet-title" style:color={color}>{item.name}</h2>

  <div class="figures">
    <span class="figure"><span class="caption">Eaten</span><span class="big" style:color={color}>{show(item.eaten)}{item.incomplete ? '*' : ''}</span></span>
    <span class="figure"><span class="caption">Target</span><span class="big">{item.target === null ? '—' : show(item.target)}</span></span>
    <span class="figure">
      <span class="caption">{item.remaining !== null && item.remaining < 0 ? 'Over' : 'Left'}</span>
      <span class="big">{item.remaining === null ? '—' : show(Math.abs(item.remaining))}</span>
    </span>
  </div>

  {#if item.target === null}
    <button type="button" class="secondary-button pressable" onclick={onsettargets}>Set targets</button>
  {/if}

  {#if item.incomplete}
    <p class="note">* May be low: {missing.length === 1 ? `${missing[0].food_name} doesn't` : `${missing.length} foods don't`} list {item.name.toLowerCase()}, so {missing.length === 1 ? "it isn't" : "they aren't"} counted.</p>
  {/if}

  <section class="stack">
    <h3 class="section-heading">Where it came from</h3>
    {#if rows.length}
      <div class="list">
        {#each rows as row (row.entry.id)}
          <div class="list-row">
            <span class="row-text">
              <span class="row-name">{row.entry.food_name}</span>
              <span class="note">{row.entry.meal_label}{isOneOff(row.entry) ? '' : ` · ${quantityText(row.entry.quantity, row.entry.unit)}`}</span>
            </span>
            <span class="row-value">{show(row.value)}</span>
          </div>
        {/each}
      </div>
    {:else}
      <p class="note">Nothing logged with {item.name.toLowerCase()} yet.</p>
    {/if}
  </section>
</Sheet>

<style>
  .sheet-title {
    padding-top: 6px;
    font: 800 26px/1.1 var(--display);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .figures {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    padding: 14px;
    border-radius: 14px;
    background: var(--card);
  }

  .figure {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .caption {
    font: 700 12px/1 var(--display);
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .big {
    font: 800 22px/1.05 var(--display);
  }

  .row-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding: 6px 0;
  }

  .row-name {
    font-size: 15px;
    font-weight: 600;
  }

  .row-value {
    flex: none;
    font: 800 17px/1 var(--display);
  }
</style>
