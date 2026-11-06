<script>
  // One nutrient day by day: a bar for what you ate, a short line for that day's target, and a dot for Garmin's
  // burn where there is one. A day with nothing logged is left empty, never drawn as zero. Tap a day to read it.
  import { amountText } from '../lib/food.js';
  import { shortDate } from '../lib/format.js';

  // items: [{ date, value | null, target | null, burn | null }]
  let { items, unit, color = 'var(--ink)', label, showBurn = false } = $props();

  const WIDTH = 346;
  const HEIGHT = 150;
  const LEFT = 34;
  const RIGHT = 6;
  const TOP = 10;
  const BOTTOM = 20;

  let picked = $state(null);

  const top = $derived.by(() => {
    const all = items.flatMap((d) => [d.value, d.target, showBurn ? d.burn : null]).filter((v) => Number.isFinite(v));
    const high = Math.max(1, ...all);
    const step = 10 ** Math.floor(Math.log10(high));
    return Math.ceil(high / step) * step;
  });
  const plot = HEIGHT - TOP - BOTTOM;
  const y = (v) => TOP + ((top - v) / top) * plot;
  const band = $derived((WIDTH - LEFT - RIGHT) / Math.max(items.length, 1));
  const barWidth = $derived(Math.max(4, Math.min(22, band * 0.6)));
  const shown = $derived(picked ?? items.length - 1);
  const unitText = (v) => `${amountText(v, unit)} ${unit}`;

  function pick(event) {
    const box = event.currentTarget.getBoundingClientRect();
    const position = ((event.clientX - box.left) / box.width) * WIDTH;
    picked = Math.max(0, Math.min(items.length - 1, Math.floor((position - LEFT) / band)));
  }
</script>

<div class="readout">
  {#if items.length}
    {@const day = items[shown]}
    <span>{shortDate(day.date)}</span>
    {#if day.value === null}
      <b>Nothing logged</b>
    {:else}
      <span>Ate <b>{unitText(day.value)}</b></span>
    {/if}
    {#if day.target !== null}<span>Target <b>{unitText(day.target)}</b></span>{/if}
    {#if showBurn && day.burn !== null}<span>Burned <b>{unitText(day.burn)}</b> <i class="tag">GARMIN, ESTIMATE</i></span>{/if}
  {/if}
</div>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<svg
  viewBox="0 0 {WIDTH} {HEIGHT}"
  role="img"
  aria-label={label}
  onpointerdown={pick}
  onpointermove={(e) => e.buttons && pick(e)}
  onpointerup={() => (picked = null)}
  onpointerleave={() => (picked = null)}
>
  {#each [top, top / 2, 0] as tick (tick)}
    <line x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} stroke="var(--track)" />
    <text x={LEFT - 6} y={y(tick) + 4} text-anchor="end" class="tick">{amountText(tick, unit)}</text>
  {/each}
  {#each items as day, i (day.date)}
    {@const x = LEFT + i * band + band / 2}
    {@const faded = picked !== null && picked !== i}
    {#if day.value !== null && day.value > 0}
      <rect x={x - barWidth / 2} y={y(day.value)} width={barWidth} height={y(0) - y(day.value)} rx="3" fill={color} opacity={faded ? 0.4 : 1} />
    {:else if day.value === null}
      <line x1={x - barWidth / 2} x2={x + barWidth / 2} y1={y(0)} y2={y(0)} stroke="var(--border)" stroke-dasharray="2 2" />
    {/if}
    {#if day.target !== null}
      <line x1={x - barWidth / 2 - 3} x2={x + barWidth / 2 + 3} y1={y(day.target)} y2={y(day.target)} stroke="var(--ink-2)" stroke-width="2" stroke-linecap="round" opacity={faded ? 0.4 : 1} />
    {/if}
    {#if showBurn && day.burn !== null}
      <circle cx={x} cy={y(day.burn)} r="3" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.5" opacity={faded ? 0.4 : 1} />
    {/if}
  {/each}
  {#if items.length}
    <text x={LEFT} y={HEIGHT - 4} class="tick">{shortDate(items[0].date)}</text>
    <text x={WIDTH - RIGHT} y={HEIGHT - 4} text-anchor="end" class="tick">{shortDate(items.at(-1).date)}</text>
  {/if}
</svg>

<style>
  svg {
    display: block;
    width: 100%;
    height: auto;
    touch-action: pan-y;
  }

  .tick {
    font: 400 11px var(--body);
    fill: var(--ink-3);
    font-variant-numeric: tabular-nums;
  }

  .readout {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 12px;
    min-height: 18px;
    font-size: 12px;
    color: var(--ink-2);
  }

  b {
    color: var(--ink);
    font-weight: 600;
  }

  i {
    font-style: normal;
  }
</style>
