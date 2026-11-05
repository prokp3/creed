<script>
  // Columns with stacked parts: a 2px gap between parts, and a rounded top only. Tap a column to read it.
  let {
    items,
    label,
    format = (v) => String(Math.round(v)),
    line = null,
    lineLabel = '',
    step = 50,
    barWidth = 16,
    height = 150,
    firstLabel = '',
    lastLabel = '',
  } = $props();

  const WIDTH = 346;
  const LEFT = 28;
  const RIGHT = 8;
  const TOP = 18;
  const BOTTOM = 20;

  let picked = $state(null);

  const totals = $derived(items.map((item) => item.parts.reduce((sum, p) => sum + (p.value || 0), 0)));
  const top = $derived(Math.max(step, Math.ceil(Math.max(0, ...totals, line ?? 0) / step) * step));
  const plot = $derived(height - TOP - BOTTOM);
  const y = (v) => TOP + ((top - v) / top) * plot;
  const band = $derived((WIDTH - LEFT - RIGHT) / Math.max(items.length, 1));

  function columns(list) {
    return list.map((item, index) => {
      const left = LEFT + index * band + (band - barWidth) / 2;
      let base = y(0);
      const parts = item.parts.filter((p) => p.value > 0);
      const shapes = parts.map((p, i) => {
        const size = (p.value / top) * plot;
        const roof = base - size;
        const radius = i === parts.length - 1 ? Math.min(4, size) : 0;
        const d = radius
          ? `M${left} ${base} V${roof + radius} Q${left} ${roof} ${left + radius} ${roof} H${left + barWidth - radius} Q${left + barWidth} ${roof} ${left + barWidth} ${roof + radius} V${base} Z`
          : `M${left} ${base} V${roof} H${left + barWidth} V${base} Z`;
        base = roof - 2;
        return { d, color: p.color };
      });
      return { shapes, left, top: base };
    });
  }

  const drawn = $derived(columns(items));
  const shown = $derived(picked ?? items.length - 1);

  function pick(event) {
    const box = event.currentTarget.getBoundingClientRect();
    const position = ((event.clientX - box.left) / box.width) * WIDTH;
    picked = Math.max(0, Math.min(items.length - 1, Math.floor((position - LEFT) / band)));
  }
</script>

<div class="readout">
  {#if items.length}
    <span>{items[shown].label}</span>
    {#if items[shown].parts.some((p) => p.value > 0)}
      {#each items[shown].parts.filter((p) => p.value > 0) as p (p.name)}
        <span class="reading">
          {#if items[shown].parts.length > 1}<i style:background={p.color}></i>{/if}
          {p.name} <b>{format(p.value)}</b>
        </span>
      {/each}
    {:else}
      <b>{items[shown].empty ?? '0'}</b>
    {/if}
  {/if}
</div>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<svg
  viewBox="0 0 {WIDTH} {height}"
  role="img"
  aria-label={label}
  onpointerdown={pick}
  onpointermove={(e) => e.buttons && pick(e)}
  onpointerup={() => (picked = null)}
  onpointerleave={() => (picked = null)}
>
  {#each [top, top / 2, 0] as tick (tick)}
    <line x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} stroke="var(--track)" />
    <text x={LEFT - 6} y={y(tick) + 4} text-anchor="end" class="tick">{tick}</text>
  {/each}
  {#each drawn as column, index (index)}
    {#each column.shapes as shape, i (i)}
      <path d={shape.d} fill={shape.color} opacity={picked !== null && picked !== index ? 0.45 : 1} />
    {/each}
  {/each}
  {#if line !== null}
    <line x1={LEFT} x2={WIDTH - RIGHT} y1={y(line)} y2={y(line)} stroke="var(--ink-3)" />
    <text x={WIDTH - RIGHT} y={y(line) - 4} text-anchor="end" class="line-label">{lineLabel}</text>
  {/if}
  <text x={LEFT} y={height - 4} class="tick">{firstLabel}</text>
  <text x={WIDTH - RIGHT} y={height - 4} text-anchor="end" class="tick">{lastLabel}</text>
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

  .line-label {
    font: 400 11px var(--body);
    fill: var(--ink-2);
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
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }

  b {
    color: var(--ink);
    font-weight: 600;
  }
</style>
