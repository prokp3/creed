<script>
  import DisciplineRing from '../components/DisciplineRing.svelte';
  import Icon from '../components/Icon.svelte';
  import Screen from '../components/Screen.svelte';
  import StatusNote from '../components/StatusNote.svelte';
  import { distance, duration, localClock, pace, shortDate, titleCase, whole } from '../lib/format.js';
  import { resource } from '../lib/resource.svelte.js';

  let { id } = $props();

  const res = resource(() => `/api/activities/${id}`);
  const a = $derived(res.data);

  $effect(() => {
    id;
    res.load();
  });

  const LOAD_METHOD = {
    samples: 'Heart-rate reserve, from every recorded sample',
    average: 'Heart-rate reserve, from average HR',
    swim: 'Duration, distance and pace. Wrist HR is not used for swims',
    none: "Couldn't be worked out",
  };

  const rows = $derived.by(() => {
    if (!a) return [];
    const list = [
      ['Distance', distance(a.discipline, a.distance_m)],
      ['Time', duration(a.duration_seconds)],
      ['Moving time', duration(a.moving_seconds)],
      [a.discipline === 'bike' ? 'Average speed' : 'Average pace', pace(a.discipline, a.avg_speed_mps)],
    ];
    if (a.discipline !== 'swim') {
      list.push(['Average HR', a.avg_hr ? `${whole(a.avg_hr)} bpm` : '—'], ['Max HR', a.max_hr ? `${whole(a.max_hr)} bpm` : '—']);
    }
    if (a.avg_power) list.push(['Average power', `${whole(a.avg_power)} W`]);
    if (a.norm_power) list.push(['Normalized power', `${whole(a.norm_power)} W`]);
    if (a.discipline === 'swim') {
      if (a.pool_length_m) list.push(['Pool length', `${whole(a.pool_length_m)} m`]);
      if (a.active_lengths) list.push(['Lengths', whole(a.active_lengths)]);
      if (a.avg_swolf) list.push(['SWOLF', whole(a.avg_swolf)]);
    }
    return list.filter(([, value]) => value !== '—');
  });

  const garmin = $derived.by(() => {
    if (!a) return [];
    return [
      ['Training Load', a.garmin_load === null ? null : whole(a.garmin_load)],
      ['Aerobic effect', a.aerobic_effect === null ? null : a.aerobic_effect.toFixed(1)],
      ['Anaerobic effect', a.anaerobic_effect === null ? null : a.anaerobic_effect.toFixed(1)],
    ].filter(([, value]) => value !== null);
  });
</script>

<Screen>
  <div class="gutter top">
    <a class="back pressable" href="#/activities" aria-label="Back to activities"><Icon name="back" size={22} stroke={2.4} /></a>
    <h1 class="page-heading">{a ? titleCase(a.type_key) : 'Activity'}</h1>
  </div>

  <StatusNote resource={res} what="this activity" />

  {#if a}
    <div class="gutter summary {a.discipline}">
      <DisciplineRing discipline={a.discipline} />
      <div class="summary-text">
        <span class="distance">{distance(a.discipline, a.distance_m)}</span>
        <span class="note">{a.local_date ? shortDate(a.local_date) : ''}{a.start_time ? `, ${localClock(a.start_time, a.utc_offset_minutes)}` : ''}</span>
      </div>
      {#if a.load !== null}
        <div class="load">
          <span class="tile-value">{whole(a.load)}</span>
          <span class="tag">LOAD · COMPUTED</span>
        </div>
      {/if}
    </div>

    <section class="gutter stack">
      <div class="card list">
        {#each rows as [label, value] (label)}
          <span>{label}</span><span class="value">{value}</span>
        {/each}
      </div>
      {#if a.load_method}<p class="note">How load was worked out: {LOAD_METHOD[a.load_method]}.</p>{/if}
    </section>

    {#if a.steady}
      <section class="gutter stack">
        <h2 class="section-heading">Aerobic efficiency</h2>
        <div class="card list">
          <span>Efficiency</span><span class="value">{a.efficiency.toFixed(2)} m/min per bpm</span>
          <span>Heart-rate drift</span><span class="value">{a.decoupling_pct.toFixed(1)}%</span>
        </div>
      </section>
    {/if}

    {#if garmin.length}
      <section class="gutter stack">
        <h2 class="section-heading">Garmin</h2>
        <div class="card list">
          {#each garmin as [label, value] (label)}
            <span>{label}</span><span class="value">{value}</span>
          {/each}
        </div>
      </section>
    {/if}

    {#if a.flags.length}
      <section class="gutter stack">
        <h2 class="section-heading">Data quality</h2>
        <div class="card stack">
          {#each a.flags as flag (flag.code)}
            <span class:attention={flag.severity !== 'info'} class:note={flag.severity === 'info'}>{flag.detail}</span>
          {/each}
        </div>
      </section>
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

  .back {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    margin-left: -12px;
  }

  .summary {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .summary-text {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
  }

  .distance {
    font: 800 34px/1.05 var(--display);
  }

  .load {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    color: var(--ink);
  }

  .list {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 10px 12px;
  }

  .value {
    font-weight: 600;
    text-align: right;
  }
</style>
