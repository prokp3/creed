<script>
  // Lines on one axis. Tap or drag to read any day. A null value is a gap, never a guess.
  import { shortDate } from '../lib/format.js';

  let {
    dates,
    series,
    label,
    format = (v) => String(Math.round(v)),
    band = null,
    zero = false,
    minTop = null,
    minBottom = null,
    step = 10,
    height = 150,
  } = $props();

  const WIDTH = 346;
  const LEFT = 28;
  const RIGHT = 34;
  const TOP = 8;
  const BOTTOM = 20;

  let picked = $state(null);

  const values = $derived(series.flatMap((s) => s.values).filter((v) => v !== null && v !== undefined));
  const scale = $derived.by(() => {
    const extra = band ? band : [];
    const all = [...values, ...extra, ...(zero ? [0] : [])];
    if (!all.length) return { low: 0, high: step };
    let low = Math.floor(Math.min(...all) / step) * step;
    let high = Math.ceil(Math.max(...all) / step) * step;
    if (minTop !== null) high = Math.max(high, minTop);
    if (minBottom !== null) low = Math.min(low, minBottom);
    if (high === low) high = low + step;
    return { low, high };
  });
  const y = (v) => TOP + ((scale.high - v) / (scale.high - scale.low)) * (height - TOP - BOTTOM);
  const x = (i) => LEFT + (i * (WIDTH - LEFT - RIGHT)) / Math.max(dates.length - 1, 1);

  function path(points) {
    let out = '';
    let drawing = false;
    points.forEach((v, i) => {
      if (v === null || v === undefined) {
        drawing = false;
        return;
      }
      // A very short segment makes a lone night show as a dot.
      out += drawing ? `L${x(i).toFixed(1)} ${y(v).toFixed(1)} ` : `M${x(i).toFixed(1)} ${y(v).toFixed(1)} h0.01 `;
      drawing = true;
    });
    return out;
  }

  const lastIndex = (points) => {
    for (let i = points.length - 1; i >= 0; i -= 1) {
      if (points[i] !== null && points[i] !== undefined) return i;
    }
    return -1;
  };

  const shown = $derived(picked ?? dates.length - 1);
  const midLabel = $derived(dates.length > 2 ? shortDate(dates[Math.floor((dates.length - 1) / 2)]) : '');

  function pick(event) {
    const box = event.currentTarget.getBoundingClientRect();
    const position = ((event.clientX - box.left) / box.width) * WIDTH;
    const index = Math.round(((position - LEFT) / (WIDTH - LEFT - RIGHT)) * (dates.length - 1));
    picked = Math.max(0, Math.min(dates.length - 1, index));
  }

  function release() {
    picked = null;
  }
</script>

<div class="readout">
  <span>{dates.length ? shortDate(dates[shown]) : ''}</span>
  {#each series as s (s.name)}
    <span class="reading">
      {#if series.length > 1}<i style:background={s.color}></i>{/if}
      {s.name}
      <b>{s.values[shown] === null || s.values[shown] === undefined ? 'no record' : format(s.values[shown])}</b>
    </span>
  {/each}
</div>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<svg
  viewBox="0 0 {WIDTH} {height}"
  role="img"
  aria-label={label}
  onpointerdown={pick}
  onpointermove={(e) => e.buttons && pick(e)}
  onpointerup={release}
  onpointerleave={release}
>
  {#if band}
    <rect x={LEFT} width={WIDTH - LEFT - RIGHT} y={y(band[1])} height={y(band[0]) - y(band[1])} fill="#fff" fill-opacity="0.08" />
  {/if}
  {#each [scale.high, scale.low] as tick (tick)}
    <line x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} stroke="var(--track)" />
    <text x={LEFT - 6} y={y(tick) + 4} text-anchor="end" class="tick">{tick}</text>
  {/each}
  {#if zero && scale.low < 0 && scale.high > 0}
    <line x1={LEFT} x2={WIDTH - RIGHT} y1={y(0)} y2={y(0)} stroke="var(--ink-3)" />
    <text x={LEFT - 6} y={y(0) + 4} text-anchor="end" class="tick">0</text>
  {/if}
  {#each series as s (s.name)}
    <path d={path(s.values)} fill="none" stroke={s.color} stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    {#if lastIndex(s.values) >= 0}
      {@const end = lastIndex(s.values)}
      <circle cx={x(end)} cy={y(s.values[end])} r="4" fill={s.color} stroke="var(--card)" stroke-width="2" />
      <text x={x(end) + 8} y={y(s.values[end]) + 4} class="end" fill={s.color}>{format(s.values[end])}</text>
    {/if}
  {/each}
  {#if picked !== null}
    <line x1={x(picked)} x2={x(picked)} y1={TOP} y2={height - BOTTOM} stroke="var(--ink-2)" />
  {/if}
  {#if dates.length}
    <text x={LEFT} y={height - 4} class="tick">{shortDate(dates[0])}</text>
    <text x={(LEFT + WIDTH - RIGHT) / 2} y={height - 4} text-anchor="middle" class="tick">{midLabel}</text>
    <text x={WIDTH - RIGHT} y={height - 4} text-anchor="end" class="tick">TODAY</text>
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

  .end {
    font: 600 12px var(--body);
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

  .reading {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .reading i {
    width: 14px;
    height: 2px;
  }

  .reading b {
    color: var(--ink);
    font-weight: 600;
  }
</style>
