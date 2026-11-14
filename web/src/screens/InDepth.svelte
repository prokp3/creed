<script>
  import BarChart from '../components/BarChart.svelte';
  import DisciplineRing from '../components/DisciplineRing.svelte';
  import Icon from '../components/Icon.svelte';
  import LineChart from '../components/LineChart.svelte';
  import Screen from '../components/Screen.svelte';
  import StatusNote from '../components/StatusNote.svelte';
  import WhyPanel from '../components/WhyPanel.svelte';
  import { clock, distance, duration, shortDate, signed, titleCase, whole } from '../lib/format.js';
  import { resource } from '../lib/resource.svelte.js';

  let { active, freshness } = $props();

  const RANGES = [7, 30, 90, 180];
  const SECTION_LIST = [
    ['form', 'Form'],
    ['recovery', 'Recovery'],
    ['sleep', 'Sleep'],
    ['load', 'Load'],
    ['garmin', null],
    ['aerobic', 'Aerobic efficiency'],
    ['data', 'Data quality'],
  ];
  const DISCIPLINE_PARTS = [
    ['run', 'Run', 'var(--run)'],
    ['bike', 'Bike', 'var(--bike)'],
    ['swim', 'Swim', 'var(--swim)'],
  ];

  let days = $state(90);
  let jump = $state('form');
  const res = resource(() => `/api/in-depth?days=${days}`);
  const data = $derived(res.data);
  // Where the data comes from: Garmin, or intervals.icu for other watches. The server names it.
  const source = $derived(data?.garmin.tag ?? 'Garmin');
  // With no watch there's no source section to show.
  const noWatch = $derived(source === 'No watch');
  const sections = $derived(SECTION_LIST.filter(([id]) => !(noWatch && id === 'garmin')).map(([id, label]) => [id, label ?? source]));

  $effect(() => {
    freshness;
    days;
    if (active) res.load();
  });

  function jumpTo(event) {
    jump = event.currentTarget.value;
    document.getElementById(jump)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  const dates = (series) => series.map((point) => point.day);
  const values = (series, key = 'value') => series.map((point) => point[key]);

  const week = $derived(data?.load.weekly.at(-1));
  const weekTotal = $derived(week?.total_load ?? 0);
  const hrvBand = $derived(
    data?.recovery.hrv_balanced_low && data?.recovery.hrv_balanced_high
      ? [data.recovery.hrv_balanced_low, data.recovery.hrv_balanced_high]
      : null,
  );
  const recoveryInputs = $derived.by(() => {
    const inputs = data?.recovery.inputs;
    if (!inputs) return [];
    const rows = [];
    if (inputs.hrv) rows.push({ label: 'Overnight HRV', value: `${whole(inputs.hrv.value)} ms`, change: `${signed(inputs.hrv.z, 1)} SD` });
    if (inputs.resting_hr) rows.push({ label: 'Resting HR', value: `${whole(inputs.resting_hr.value)} bpm`, change: `${signed(inputs.resting_hr.difference)} bpm` });
    if (inputs.respiration) rows.push({ label: 'Respiration in sleep', value: `${inputs.respiration.value.toFixed(0)} /min`, change: `${signed(inputs.respiration.difference, 1)}` });
    if (inputs.sleep) {
      rows.push({
        label: 'Sleep vs need',
        value: `${Math.round(inputs.sleep.performance * 100)}%`,
        change: inputs.sleep.performance < 0.85 ? 'Short' : 'Fine',
        attention: inputs.sleep.performance < 0.85,
      });
    }
    return rows;
  });

  const sleepDetails = $derived(data?.sleep.details ?? {});
  const stages = $derived(sleepDetails.stages_seconds);
  const need = $derived(sleepDetails.need_seconds ?? null);

  const dailyBars = $derived(
    (data?.load.daily ?? []).map((row) => ({
      label: shortDate(row.day),
      parts: DISCIPLINE_PARTS.map(([key, name, color]) => ({ name, color, value: row[key] })),
    })),
  );
  const weeklyBars = $derived(
    (data?.load.weekly ?? []).map((row) => ({
      label: `Week of ${shortDate(row.week_start)}`,
      parts: DISCIPLINE_PARTS.map(([key, name, color]) => ({ name, color, value: row.disciplines[key].load })),
    })),
  );
  const sleepBars = $derived(
    (data?.sleep.nights ?? []).map((night) => ({
      label: shortDate(night.day),
      empty: 'no record',
      parts: [
        {
          name: night.flagged ? 'Partial record' : 'Sleep',
          value: night.seconds ? night.seconds / 3600 : 0,
          color: need && night.seconds && night.seconds / need < 0.85 ? 'var(--attention)' : 'var(--ink)',
        },
      ],
    })),
  );
  const garminTiles = $derived.by(() => {
    const g = data?.garmin.latest;
    if (!g) return [];
    return [
      ['Body Battery', g.body_battery_latest, (v) => whole(v), g.body_battery_charged === undefined ? '' : `${whole(g.body_battery_charged)} charged, ${whole(g.body_battery_drained)} drained`],
      ['HRV status', g.hrv_status, (v) => titleCase(v).toUpperCase(), g.hrv_weekly_avg === undefined ? '' : `7-day average ${whole(g.hrv_weekly_avg)} ms`],
      ['Stress', g.stress_avg, (v) => whole(v), 'Daily average'],
      ['Steps', g.steps, (v) => whole(v), 'Today'],
      ['Intensity minutes', g.intensity_moderate, (v) => whole(v + (g.intensity_vigorous ?? 0)), `${whole(g.intensity_moderate)} moderate, ${whole(g.intensity_vigorous)} vigorous`],
      ['Resting HR', g.resting_hr, (v) => whole(v), 'bpm'],
      ['Respiration', g.respiration_avg, (v) => whole(v), 'Daily average, /min'],
    ].filter(([, value]) => value !== undefined && value !== null);
  });
</script>

<Screen {active}>
  <div class="gutter top">
    <h1 class="page-heading">In-Depth</h1>
    <a class="gear pressable" href="#/settings" aria-label="Settings"><Icon name="settings" size={22} /></a>
  </div>

  <div class="gutter ranges" role="group" aria-label="Date range">
    {#each RANGES as range (range)}
      <button class="segment pressable" aria-pressed={days === range} onclick={() => (days = range)}>{range} D</button>
    {/each}
  </div>

  <div class="gutter jump">
    <label for="jump-to" class="tile-label">Jump to</label>
    <div class="select-wrap">
      <select id="jump-to" value={jump} onchange={jumpTo}>
        {#each sections as [id, label] (id)}
          <option value={id}>{label}</option>
        {/each}
      </select>
      <span class="select-icon"><Icon name="down" size={18} /></span>
    </div>
  </div>

  <StatusNote resource={res} />

  {#if data}
    <div class="sections" class:refreshing={res.loading}>
      <section id="form" class="gutter stack">
        <h2 class="page-heading">Form</h2>
        {#if data.form.state === 'ok'}
          <div class="grid-3">
            <div class="tile"><span class="tile-label">Fitness</span><span class="tile-value">{whole(data.form.fitness)}</span><span class="tag">CTL · COMPUTED</span></div>
            <div class="tile"><span class="tile-label">Fatigue</span><span class="tile-value">{whole(data.form.fatigue)}</span><span class="tag">ATL · COMPUTED</span></div>
            <div class="tile"><span class="tile-label">Form</span><span class="tile-value">{signed(data.form.form)}</span><span class="tag">TSB · COMPUTED</span></div>
          </div>
          <div class="card stack">
            <LineChart
              label="Fitness and fatigue over the selected period"
              dates={dates(data.form.series)}
              series={[
                { name: 'Fitness', color: 'var(--ink)', values: values(data.form.series, 'fitness') },
                { name: 'Fatigue', color: 'var(--ink-3)', values: values(data.form.series, 'fatigue') },
              ]}
              minTop={20}
              height={190}
            />
          </div>
          <div class="card stack">
            <h3 class="tile-label">Form over time</h3>
            <LineChart
              label="Form over the selected period"
              dates={dates(data.form.series)}
              series={[{ name: 'Form', color: 'var(--ink)', values: values(data.form.series, 'form') }]}
              format={(v) => signed(v)}
              zero
              height={120}
            />
          </div>
        {:else}
          <div class="tile"><span class="not-enough">Not enough data</span><span class="note">{data.form.reason}</span></div>
        {/if}
        <WhyPanel why={data.form.why} confidence={data.form.confidence} />
      </section>

      <section id="recovery" class="gutter stack">
        <h2 class="page-heading">Recovery</h2>
        <div class="card stack">
          {#if data.recovery.state === 'ok'}
            <div class="score">
              <span class="tile-value big">{whole(data.recovery.value)}</span>
              <span class="note">of 100</span>
              <span class="tag push">COMPUTED</span>
            </div>
            <div class="inputs">
              {#each recoveryInputs as row (row.label)}
                <span>{row.label}</span>
                <span class="strong" class:attention={row.attention}>{row.value}</span>
                <span class="right" class:attention={row.attention}>{row.change}</span>
              {/each}
            </div>
          {:else}
            <span class="not-enough">Not enough data</span>
            <span class="note">{data.recovery.reason}</span>
          {/if}
        </div>
        <WhyPanel why={data.recovery.why} confidence={data.recovery.confidence} />
        <div class="card stack">
          <div class="chart-head"><h3 class="tile-label">Overnight HRV, ms</h3><span class="tag">{source}{hrvBand ? ' · shaded: balanced range' : ''}</span></div>
          <LineChart label="Overnight HRV. Gaps are nights with no record." dates={dates(data.recovery.hrv)} series={[{ name: 'HRV', color: 'var(--ink)', values: values(data.recovery.hrv) }]} band={hrvBand} height={120} />
        </div>
        <div class="card stack">
          <div class="chart-head"><h3 class="tile-label">Resting HR, bpm</h3><span class="tag">{source}</span></div>
          <LineChart label="Resting heart rate. Gaps are days with no record." dates={dates(data.recovery.resting_hr)} series={[{ name: 'Resting HR', color: 'var(--ink)', values: values(data.recovery.resting_hr) }]} step={5} height={120} />
        </div>
        <div class="card stack">
          <div class="chart-head"><h3 class="tile-label">Respiration in sleep, /min</h3><span class="tag">{source}</span></div>
          <LineChart label="Respiration during sleep. Gaps are nights with no record." dates={dates(data.recovery.respiration)} series={[{ name: 'Respiration', color: 'var(--ink)', values: values(data.recovery.respiration) }]} step={2} format={(v) => v.toFixed(0)} height={120} />
        </div>
      </section>

      <section id="sleep" class="gutter stack">
        <h2 class="page-heading">Sleep</h2>
        {#if data.sleep.state === 'ok'}
          <div class="grid-3">
            <div class="tile"><span class="tile-label">Last night</span><span class="tile-value mid">{clock(data.sleep.value)}</span><span class="tag">of {clock(need)} need</span></div>
            <div class="tile"><span class="tile-label">7-day debt</span><span class="tile-value mid">{duration(sleepDetails.debt_seconds)}</span><span class="tag">COMPUTED</span></div>
            <div class="tile"><span class="tile-label">Bedtime spread</span><span class="tile-value mid">{sleepDetails.bedtime_spread_minutes === null ? '—' : `±${whole(sleepDetails.bedtime_spread_minutes)}m`}</span><span class="tag">COMPUTED</span></div>
          </div>
        {:else}
          <div class="tile"><span class="not-enough">Not enough data</span><span class="note">{data.sleep.reason}</span></div>
        {/if}
        <div class="card stack">
          <h3 class="tile-label">Last 14 nights</h3>
          <BarChart
            label="Hours slept on each of the last 14 nights. Blank nights have no record."
            items={sleepBars}
            format={(v) => clock(v * 3600)}
            line={need ? need / 3600 : null}
            lineLabel={need ? `NEED ${clock(need)}` : ''}
            step={5}
            firstLabel="−13 D"
            lastLabel="LAST NIGHT"
          />
        </div>
        {#if stages && stages.light !== null}
          <div class="card stack">
            <div class="chart-head"><h3 class="tile-label">Last night's stages</h3><span class="tag">Approximate</span></div>
            <div class="stages" role="img" aria-label={`Deep ${clock(stages.deep)}, light ${clock(stages.light)}, REM ${clock(stages.rem)}`}>
              <div style:flex="{stages.deep} 1 0" class="stage one">Deep {clock(stages.deep)}</div>
              <div style:flex="{stages.light} 1 0" class="stage two">Light {clock(stages.light)}</div>
              <div style:flex="{stages.rem} 1 0" class="stage three">REM {clock(stages.rem)}</div>
            </div>
          </div>
        {/if}
        <WhyPanel why={data.sleep.why} confidence={data.sleep.confidence} />
      </section>

      <section id="load" class="gutter stack">
        <h2 class="page-heading">Load</h2>
        <div class="legend">
          {#each DISCIPLINE_PARTS as [key, name] (key)}
            <span class={key}><i class="dot"></i>{name}</span>
          {/each}
        </div>
        <div class="card stack">
          <h3 class="tile-label">Daily, 14 days</h3>
          <BarChart label="Daily training load by discipline for the last 14 days" items={dailyBars} firstLabel="−13 D" lastLabel="TODAY" />
        </div>
        <div class="card stack">
          <h3 class="tile-label">Weekly, 8 weeks</h3>
          <BarChart label="Weekly training load by discipline for the last 8 weeks" items={weeklyBars} step={100} barWidth={24} firstLabel="−7 W" lastLabel="THIS WEEK" />
        </div>
        {#if week}
          <div class="card stack">
            <h3 class="tile-label">This week by discipline</h3>
            {#if weekTotal > 0}
              <div class="split-bar" role="img" aria-label="Share of this week's load by discipline">
                {#each DISCIPLINE_PARTS as [key] (key)}
                  <div style:flex="{week.disciplines[key].load} 1 0" style:background="var(--{key})"></div>
                {/each}
              </div>
            {/if}
            {#each DISCIPLINE_PARTS as [key, name] (key)}
              {@const row = week.disciplines[key]}
              <div class="week-row {key}">
                <DisciplineRing discipline={key} size={40} />
                <span class="week-name">{name}</span>
                <span class="week-distance">{distance(key, row.distance_m)}</span>
                <span class="small">{duration(row.seconds)}</span>
                <span class="small week-load">Load {whole(row.load)}</span>
              </div>
            {/each}
          </div>
        {/if}
        <WhyPanel why={data.load.why} confidence={data.load.confidence} />
      </section>

      {#if !noWatch}
      <section id="garmin" class="gutter stack">
        <h2 class="page-heading">{source}</h2>
        {#if garminTiles.length}
          <div class="grid-2">
            {#each garminTiles as [label, value, show, note] (label)}
              <div class="tile">
                <span class="tile-label">{label}</span>
                <span class="tile-value">{show(value)}</span>
                <span class="note">{note}</span>
              </div>
            {/each}
          </div>
        {:else}
          <p class="note">Nothing from {source} in the last two days.</p>
        {/if}
      </section>
      {/if}

      <section id="aerobic" class="gutter stack">
        <h2 class="page-heading">Aerobic efficiency</h2>
        <div class="card stack">
          {#if data.aerobic.state === 'ok'}
            <div class="score">
              <span class="tile-value big">{data.aerobic.value.toFixed(2)}</span>
              <span class="note">{data.aerobic.unit}</span>
              <span class="tag push">COMPUTED</span>
            </div>
            <div class="inputs two">
              <span>Steady runs, 42 days</span><span class="strong right">{data.aerobic.details.steady_runs}</span>
              {#if data.aerobic.details.median_drift_pct !== null}<span>Heart-rate drift</span><span class="strong right">{data.aerobic.details.median_drift_pct.toFixed(1)}%</span>{/if}
              {#if data.aerobic.details.hr_at_reference_speed !== null}<span>HR at your usual pace</span><span class="strong right">{whole(data.aerobic.details.hr_at_reference_speed)} bpm</span>{/if}
            </div>
          {:else}
            <span class="not-enough">Not enough data</span>
            <span class="note">{data.aerobic.reason}</span>
          {/if}
        </div>
        <WhyPanel why={data.aerobic.why} confidence={data.aerobic.confidence} />
      </section>

      <section id="data" class="gutter stack">
        <h2 class="page-heading">Data quality</h2>
        <div class="card stack">
          {#if data.data_quality.issues.length}
            {#each data.data_quality.issues as issue, i (i)}
              <div class="quality-row">
                <span class:attention={issue.severity === 'problem' || issue.severity === 'warning'}>{issue.detail}</span>
                <span class="tag">{issue.day ? shortDate(issue.day) : ''}</span>
              </div>
            {/each}
          {:else}
            <span class="note">No data problems in the last 7 days.</span>
          {/if}
        </div>
      </section>
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

  .ranges {
    display: flex;
    gap: 6px;
  }

  .jump {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .jump label {
    flex-shrink: 0;
  }

  .select-wrap {
    position: relative;
    flex: 1;
  }

  select {
    width: 100%;
    height: 44px;
    padding: 0 36px 0 12px;
    -webkit-appearance: none;
    appearance: none;
    border: 0;
    border-radius: 8px;
    background: var(--card);
    /* iOS zooms the page when a field's text is under 16px. */
    font: 700 16px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .select-icon {
    position: absolute;
    right: 12px;
    top: 13px;
    display: flex;
    pointer-events: none;
    color: var(--ink-2);
  }

  .sections {
    display: flex;
    flex-direction: column;
    gap: 28px;
    padding-top: 8px;
    transition: opacity 0.15s ease;
  }

  .sections.refreshing {
    opacity: 0.6;
  }

  section {
    /* Leaves room for the slim countdown when jumping to a section. */
    scroll-margin-top: 48px;
  }

  .score {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }

  .tile-value.big {
    font-size: 44px;
    line-height: 1;
  }

  .tile-value.mid {
    font-size: 26px;
    line-height: 1.1;
    white-space: nowrap;
  }

  .push {
    margin-left: auto;
  }

  .inputs {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto 72px;
    gap: 8px 12px;
    align-items: baseline;
  }

  .inputs.two {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .strong {
    font-weight: 600;
  }

  .right {
    text-align: right;
    color: var(--ink-2);
  }

  .right.strong {
    color: var(--ink);
  }

  .right.attention {
    color: var(--attention);
  }

  .chart-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
  }

  .stages {
    display: flex;
    gap: 2px;
    height: 28px;
  }

  .stage {
    display: flex;
    align-items: center;
    padding: 0 6px;
    border-radius: 4px;
    overflow: hidden;
    white-space: nowrap;
    font-size: 11px;
    font-weight: 600;
    min-width: 0;
  }

  .stage.one {
    background: var(--ink);
    color: var(--paper-ink);
  }

  .stage.two {
    background: var(--ink-2);
    color: var(--paper-ink);
  }

  .stage.three {
    background: #5a5a64;
    color: var(--ink);
  }

  .legend {
    display: flex;
    gap: 14px;
    font: 700 13px/1 var(--display);
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .legend span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .dot {
    width: 10px;
    height: 10px;
    border: 2px solid currentColor;
    border-radius: 50%;
  }

  .week-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .week-name {
    width: 36px;
    font: 700 15px/1 var(--display);
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .week-distance {
    flex: 1;
    font: 800 22px/1 var(--display);
    white-space: nowrap;
  }

  .small {
    font-size: 12px;
    white-space: nowrap;
  }

  .week-load {
    width: 52px;
    text-align: right;
  }

  .quality-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
  }
</style>
