<script>
  // Food over the last 7 or 30 days. Days with nothing logged are gaps, and averages say how many days they cover.
  import Sheet from './Sheet.svelte';
  import TrendChart from './TrendChart.svelte';
  import { amountText, localDate } from '../lib/food.js';
  import { resource } from '../lib/resource.svelte.js';

  let { onclose } = $props();

  let range = $state(7);
  const res = resource(() => `/api/food/trends?days=${range}&end=${localDate()}`);
  const data = $derived(res.data);

  $effect(() => {
    range;
    res.load();
  });

  const series = (id) =>
    (data?.days ?? []).map((d) => ({
      date: d.date,
      value: d.totals ? (d.totals[id] ?? 0) : null,
      target: d.targets?.[id] ?? null,
      burn: id === 'kcal' ? d.burned_kcal : null,
    }));
  const hasBurn = $derived((data?.days ?? []).some((d) => d.burned_kcal !== null));
  const others = $derived((data?.nutrients ?? []).filter((n) => n.id !== 'kcal' && n.id !== 'protein'));
  const show = (value, unit) => (value === null || value === undefined ? '—' : `${amountText(value, unit)} ${unit}`);
  const net = (value) => (value === null ? '—' : `${value > 0 ? '+' : value < 0 ? '−' : ''}${amountText(Math.abs(value), 'kcal')} kcal`);
</script>

<Sheet label="Food trends" {onclose} tall>
  <h2 class="sheet-title">Trends</h2>
  <div class="segments" role="group" aria-label="Days">
    {#each [7, 30] as days (days)}
      <button type="button" class="segment-button pressable" aria-pressed={range === days} onclick={() => (range = days)}>{days} days</button>
    {/each}
  </div>

  {#if res.error && !data}
    <p class="note" role="alert">{res.error.message}</p>
  {:else if !data}
    <p class="note" role="status">Loading…</p>
  {:else}
    <p class="note">
      {data.logged_days} of {data.days.length} days logged. Averages count only days you logged, since a day with nothing logged is unknown, not a day of eating nothing.
    </p>

    <div class="card stack">
      <h3 class="tile-label">Calories</h3>
      <TrendChart items={series('kcal')} unit="kcal" label="Calories eaten each day against that day's target" showBurn={hasBurn} />
      <div class="figures">
        <span class="figure"><span class="caption">Average eaten</span><span class="big">{show(data.averages.kcal?.eaten, 'kcal')}</span></span>
        <span class="figure"><span class="caption">Average target</span><span class="big">{show(data.averages.kcal?.target, 'kcal')}</span></span>
      </div>
      {#if data.net.days}
        <p class="note">
          Eaten minus Garmin's burn: <b>{net(data.net.average_kcal)}</b> a day on average, over {data.net.days} {data.net.days === 1 ? 'day' : 'days'} with both. Garmin's burn is an estimate.
        </p>
      {/if}
      <p class="tag">BARS: EATEN · LINE: TARGET{hasBurn ? ' · DOT: GARMIN BURN' : ''}</p>
    </div>

    <div class="card stack">
      <h3 class="tile-label protein">Protein</h3>
      <TrendChart items={series('protein')} unit="g" color="var(--protein)" label="Protein eaten each day against that day's target" />
      <div class="figures">
        <span class="figure"><span class="caption">Average eaten</span><span class="big protein">{show(data.averages.protein?.eaten, 'g')}</span></span>
        <span class="figure"><span class="caption">Target met</span><span class="big">{data.protein_target_met.of ? `${data.protein_target_met.days} of ${data.protein_target_met.of} days` : '—'}</span></span>
      </div>
    </div>

    <div class="list">
      {#each others as n (n.id)}
        <div class="list-row">
          <span>{n.name}</span>
          <span class="avg">{show(data.averages[n.id]?.eaten, n.unit)}{data.averages[n.id]?.target ? ` of ${show(data.averages[n.id].target, n.unit)}` : ''} a day</span>
        </div>
      {/each}
    </div>
  {/if}
</Sheet>

<style>
  .sheet-title {
    padding-top: 6px;
    font: 800 26px/1.1 var(--display);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .segments {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    padding: 3px;
    border-radius: 12px;
    background: var(--raised);
  }

  .segment-button {
    height: 44px;
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--ink-2);
    font: 800 16px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .segment-button[aria-pressed='true'] {
    background: var(--ink);
    color: var(--bg);
  }

  .card {
    border-radius: 14px;
  }

  .figures {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .figure {
    display: flex;
    flex-direction: column;
    gap: 3px;
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

  .protein {
    color: var(--protein);
  }

  .avg {
    font-size: 13px;
    text-align: right;
  }

  b {
    color: var(--ink);
    font-weight: 600;
  }
</style>
