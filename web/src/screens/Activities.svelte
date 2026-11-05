<script>
  import DisciplineRing from '../components/DisciplineRing.svelte';
  import Icon from '../components/Icon.svelte';
  import Screen from '../components/Screen.svelte';
  import StatusNote from '../components/StatusNote.svelte';
  import { get } from '../lib/api.js';
  import { distance, localClock, pace, relativeDay, titleCase, whole, zonedDate } from '../lib/format.js';
  import { race } from '../lib/race.svelte.js';
  import { resource } from '../lib/resource.svelte.js';

  let { active, freshness } = $props();

  const PAGE = 30;
  const FILTERS = [
    [null, 'All'],
    ['swim', 'Swim'],
    ['bike', 'Bike'],
    ['run', 'Run'],
  ];

  let filter = $state(null);
  let more = $state([]);
  let finished = $state(false);
  let loadingMore = $state(false);

  const path = (offset) =>
    `/api/activities?limit=${PAGE}&offset=${offset}${filter ? `&discipline=${filter}` : ''}`;
  const res = resource(() => path(0));

  $effect(() => {
    freshness;
    filter;
    if (active) {
      more = [];
      finished = false;
      res.load();
    }
  });

  const firstPage = $derived(res.data?.activities ?? []);
  const rows = $derived([...firstPage, ...more]);
  const today = $derived(race.timeZone ? zonedDate(new Date().toISOString(), race.timeZone) : null);
  const canLoadMore = $derived(!finished && firstPage.length === PAGE);

  async function loadMore() {
    loadingMore = true;
    try {
      const next = (await get(path(rows.length))).activities;
      more = [...more, ...next];
      if (next.length < PAGE) finished = true;
    } finally {
      loadingMore = false;
    }
  }

  function detail(row) {
    const parts = [distance(row.discipline, row.distance_m)];
    if (row.avg_speed_mps && ['swim', 'bike', 'run'].includes(row.discipline)) {
      parts.push(pace(row.discipline, row.avg_speed_mps));
    }
    // Swim HR isn't used anywhere because wrist HR is unreliable in water.
    if (row.avg_hr && row.discipline !== 'swim') parts.push(`${whole(row.avg_hr)} bpm`);
    return parts.filter((p) => p !== '—').join(' · ');
  }
</script>

<Screen {active}>
  <div class="gutter top">
    <h1 class="page-heading">Activities</h1>
    <a class="gear pressable" href="#/settings" aria-label="Settings"><Icon name="settings" size={22} /></a>
  </div>

  <div class="gutter filters" role="group" aria-label="Filter by discipline">
    {#each FILTERS as [value, label] (label)}
      <button class="segment pressable" aria-pressed={filter === value} onclick={() => (filter = value)}>{label}</button>
    {/each}
  </div>

  <StatusNote resource={res} />

  {#if res.data}
    <div class="gutter stack" class:refreshing={res.loading}>
      {#each rows as row (row.activity_id)}
        <a class="row pressable" href="#/activities/{row.activity_id}">
          <DisciplineRing discipline={row.discipline} size={40} />
          <span class="text">
            <span class="head">
              <span class="name {row.discipline}">{titleCase(row.type_key)}</span>
              <span class="when">
                {today ? relativeDay(row.local_date, today) : row.local_date}{row.start_time ? `, ${localClock(row.start_time, row.utc_offset_minutes)}` : ''}
              </span>
            </span>
            <span class="note">{detail(row)}</span>
          </span>
          {#if row.load !== null}<span class="load">Load {whole(row.load)}</span>{/if}
        </a>
      {:else}
        <p class="note">No activities here yet.</p>
      {/each}
      {#if canLoadMore}
        <button class="segment more pressable" disabled={loadingMore} onclick={loadMore}>
          {loadingMore ? 'Loading…' : 'Show more'}
        </button>
      {/if}
    </div>
  {/if}
</Screen>

<style>
  .top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 44px;
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

  .filters {
    display: flex;
    gap: 6px;
  }

  .filters .segment {
    flex: 1;
  }

  .refreshing {
    opacity: 0.6;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 60px;
    padding: 8px 12px;
    border-radius: 8px;
    background: var(--card);
  }

  .text {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
  }

  .head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
  }

  .name {
    font: 700 15px/1.2 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .when {
    font-size: 12px;
    color: var(--ink-3);
    white-space: nowrap;
  }

  .load {
    flex-shrink: 0;
    font-size: 12px;
    font-weight: 600;
  }

  .more {
    width: 100%;
  }
</style>
