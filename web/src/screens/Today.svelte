<script>
  import DisciplineRing from '../components/DisciplineRing.svelte';
  import Icon from '../components/Icon.svelte';
  import Ring from '../components/Ring.svelte';
  import Screen from '../components/Screen.svelte';
  import StatusNote from '../components/StatusNote.svelte';
  import {
    clock,
    dayHeading,
    distance,
    duration,
    relativeDay,
    restingDifference,
    shortDate,
    signed,
    titleCase,
    whole,
    zonedClock,
    zonedDate,
  } from '../lib/format.js';
  import { resource } from '../lib/resource.svelte.js';

  let { active, freshness } = $props();

  const DISCIPLINES = ['swim', 'bike', 'run'];
  const res = resource(() => '/api/today');
  const data = $derived(res.data);

  $effect(() => {
    freshness;
    if (active) res.load();
  });

  let showHidden = $state(false);

  function ringText(ring) {
    if (ring.key === 'sleep') return { value: clock(ring.value), sub: `OF ${clock(ring.need_seconds)}` };
    if (ring.key === 'recovery') return { value: whole(ring.value), sub: 'OF 100' };
    if (ring.key === 'resting_hr') return { value: whole(ring.value), sub: 'BPM' };
    return { value: whole(ring.value), sub: 'LOAD' };
  }

  const hiddenTitle = $derived(
    data ? `${data.hidden.map((h) => h.label).join(' and ')} hidden` : '',
  );

  const syncText = $derived.by(() => {
    if (!data) return { text: '', attention: false };
    const zone = data.race.timezone;
    const run = data.sync.latest_run;
    const good = data.sync.last_good_finish;
    if (run && ['failed', 'auth_failed'].includes(run.status)) {
      return { text: run.status === 'auth_failed' ? 'Garmin key problem' : 'Sync failed', attention: true };
    }
    if (!good) return { text: 'Not synced yet', attention: false };
    const day = zonedDate(good, zone);
    return {
      text: `Synced ${day === data.today ? zonedClock(good, zone) : shortDate(day)}`,
      attention: false,
    };
  });

  const garminTiles = $derived(
    data
      ? [
          { label: 'Body Battery', value: data.garmin.body_battery === null ? null : whole(data.garmin.body_battery) },
          { label: 'Sleep score', value: data.garmin.sleep_score === null ? null : whole(data.garmin.sleep_score) },
          { label: 'HRV status', value: data.garmin.hrv_status ?? null, text: true },
          { label: 'Stress', value: data.garmin.stress === null ? null : whole(data.garmin.stress) },
        ].filter((t) => t.value !== null && t.value !== undefined)
      : [],
  );

  const weekTotal = $derived(
    data?.week_by_discipline ? DISCIPLINES.reduce((sum, d) => sum + data.week_by_discipline[d].load, 0) : 0,
  );

  const spark = $derived.by(() => {
    const points = data?.fitness.series_30_days ?? [];
    if (points.length < 2) return null;
    const values = points.map((p) => p.fitness);
    const low = Math.min(...values);
    const high = Math.max(...values);
    const x = (i) => 4 + (i * 142) / (points.length - 1);
    const y = (v) => 50 - ((v - low) / Math.max(high - low, 0.001)) * 44;
    return {
      path: values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' '),
      endX: x(values.length - 1),
      endY: y(values[values.length - 1]),
    };
  });
</script>

<Screen {active}>
  <div class="top gutter">
    <h1 class="page-heading">{data ? dayHeading(data.today) : 'Today'}</h1>
    <span class="sync" class:attention={syncText.attention}>{syncText.text}</span>
    <a class="gear pressable" href="#/settings" aria-label="Settings"><Icon name="settings" size={22} /></a>
  </div>

  <StatusNote resource={res} />

  {#if data}
    <div class="gutter rings" class:two={data.rings.length === 2}>
      {#each data.rings as ring (ring.key)}
        {@const text = ringText(ring)}
        <Ring
          value={text.value}
          sub={text.sub}
          fraction={ring.fraction}
          label={ring.label}
          tag={ring.tag === 'Garmin' ? 'Garmin' : 'COMPUTED'}
          attention={ring.attention}
          full={ring.key === 'resting_hr'}
        />
      {/each}
    </div>

    {#if data.hidden.length}
      <div class="gutter stack">
        <button class="hidden-row pressable" aria-expanded={showHidden} onclick={() => (showHidden = !showHidden)}>
          <span class="hidden-text">
            <span class="tile-label">{hiddenTitle}</span>
            <span class="note">Not enough data yet. They come back on their own.</span>
          </span>
          <span class="chevron" class:open={showHidden}><Icon name="down" size={18} /></span>
        </button>
        {#if showHidden}
          <div class="stack">
            {#each data.hidden as item (item.key)}
              <div class="tile">
                <span class="tile-label">{item.label}</span>
                <span class="note">{item.reason}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    {#if data.tiles.resting_hr || data.tiles.sleep_vs_need}
      <div class="gutter grid-2">
        {#if data.tiles.resting_hr}
          <div class="tile">
            <span class="tile-label">Resting HR</span>
            <span class="tile-value small">{whole(data.tiles.resting_hr.value)} bpm</span>
            <span class="note">{restingDifference(data.tiles.resting_hr.difference)}</span>
          </div>
        {/if}
        {#if data.tiles.sleep_vs_need}
          {@const sleep = data.tiles.sleep_vs_need}
          <div class="tile">
            <span class="tile-label" class:attention={sleep.attention}>Sleep vs need</span>
            <span class="tile-value small" class:attention={sleep.attention}>{Math.round(sleep.performance * 100)}%</span>
            <span class="note">{duration(sleep.seconds)} of {duration(sleep.need_seconds)}</span>
          </div>
        {/if}
      </div>
    {/if}

    <section class="gutter stack">
      <h2 class="section-heading">Today</h2>
      <div class="today-row card">
        {#each DISCIPLINES as d (d)}
          {@const row = data.today_by_discipline[d]}
          <div class="today-item {d}">
            <DisciplineRing discipline={d} size={28} label={d} />
            <div class="today-text">
              <span class="today-value">{row.activities ? distance(d, row.distance_m) : 'Rest'}</span>
              <span class="small-note">Load {whole(row.load)}</span>
            </div>
          </div>
        {/each}
      </div>
    </section>

    <section class="gutter stack">
      <h2 class="section-heading">Week by discipline</h2>
      {#if data.week_by_discipline}
        {#if weekTotal > 0}
          <div class="split-bar" role="img" aria-label="Share of this week's load by discipline">
            {#each DISCIPLINES as d (d)}
              <div style:flex="{data.week_by_discipline[d].load} 1 0" style:background="var(--{d})"></div>
            {/each}
          </div>
        {/if}
        <div class="grid-3">
          {#each DISCIPLINES as d (d)}
            {@const row = data.week_by_discipline[d]}
            <div class="week-item {d}">
              <DisciplineRing discipline={d} />
              <span class="week-name">{d}</span>
              <span class="week-value">{distance(d, row.distance_m)}</span>
              <span class="small-note">Load {whole(row.load)}</span>
            </div>
          {/each}
        </div>
      {:else}
        <p class="note">No swim, bike or run in the last 8 weeks.</p>
      {/if}
    </section>

    {#if garminTiles.length}
      <section class="gutter stack">
        <h2 class="section-heading">Garmin</h2>
        <div class="grid-2">
          {#each garminTiles as tile (tile.label)}
            <div class="tile">
              <span class="tile-label">{tile.label}</span>
              <span class="tile-value">{tile.text ? titleCase(tile.value).toUpperCase() : tile.value}</span>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    {#if data.fitness.state === 'ok'}
      <div class="gutter">
        <a class="card fitness pressable" href="#/in-depth">
          <div class="fitness-text">
            <span class="tile-label">Fitness trend</span>
            <span class="tile-value">{whole(data.fitness.value)}</span>
            <span class="tag">
              COMPUTED{data.fitness.change_42_days === null ? '' : ` · ${signed(data.fitness.change_42_days, 1)} IN 42 DAYS`}
            </span>
          </div>
          {#if spark}
            <svg width="150" height="56" viewBox="0 0 150 56" role="img" aria-label="Fitness over the last 30 days">
              <path d={spark.path} fill="none" stroke="var(--ink)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              <circle cx={spark.endX} cy={spark.endY} r="4" fill="var(--ink)" stroke="var(--card)" stroke-width="2" />
            </svg>
          {/if}
        </a>
      </div>
    {/if}

    <div class="gutter">
      <div class="tile">
        <span class="tile-label">Aerobic efficiency</span>
        {#if data.aerobic.state === 'ok'}
          <span class="tile-value">{data.aerobic.value.toFixed(2)}</span>
          <span class="tag">COMPUTED · {data.aerobic.unit}</span>
        {:else}
          <span class="not-enough">Not enough data</span>
          <span class="note">{data.aerobic.reason}</span>
        {/if}
      </div>
    </div>

    {#if data.issues.length}
      <div class="gutter">
        <a class="issue pressable" href="#/in-depth">
          <span class="attention"><Icon name="warning" size={20} /></span>
          <span class="issue-text">
            <span class="issue-count attention">{data.issues.length} data {data.issues.length === 1 ? 'issue' : 'issues'}</span>
            <span class="note">
              {#if data.issues[0].day}{relativeDay(data.issues[0].day, data.today)}: {/if}{data.issues[0].detail}
            </span>
          </span>
        </a>
      </div>
    {/if}
  {/if}
</Screen>

<style>
  .top {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 44px;
  }

  .sync {
    margin-left: auto;
    font-size: 12px;
    color: var(--ink-3);
  }

  .sync.attention {
    color: var(--attention);
    font-weight: 600;
  }

  .gear {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    margin-right: -10px;
    color: var(--ink-2);
  }

  .rings {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }

  .rings.two {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .hidden-row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: 44px;
    padding: 8px 12px;
    border: 0;
    border-radius: 8px;
    background: var(--card);
    text-align: left;
  }

  .hidden-text {
    display: flex;
    flex-direction: column;
    flex: 1;
  }

  .chevron {
    display: flex;
    color: var(--ink-2);
    transition: transform 0.15s ease;
  }

  .chevron.open {
    transform: rotate(180deg);
  }

  .tile-value.small {
    font-size: 28px;
    line-height: 1.1;
  }

  .today-row {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    padding: 10px 12px;
  }

  .today-item {
    display: flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
  }

  .today-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .today-value {
    font: 800 17px/1.1 var(--display);
    white-space: nowrap;
  }

  .small-note {
    font-size: 12px;
  }

  .week-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    min-width: 0;
  }

  .week-name {
    font: 700 14px/1.2 var(--display);
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .week-value {
    font: 800 26px/1 var(--display);
    white-space: nowrap;
  }

  .fitness {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
  }

  .fitness-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex-shrink: 0;
  }

  .issue {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 44px;
    padding: 8px 12px;
    border: 1px solid var(--attention);
    border-radius: 8px;
  }

  .issue-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .issue-count {
    font-weight: 600;
  }
</style>
