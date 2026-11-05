<script>
  // Each change saves on its own, the way a phone's settings do. There's no Save button.
  import Icon from '../components/Icon.svelte';
  import Screen from '../components/Screen.svelte';
  import StatusNote from '../components/StatusNote.svelte';
  import { put } from '../lib/api.js';
  import { to12Hour, to24Hour, whole } from '../lib/format.js';
  import { resource } from '../lib/resource.svelte.js';

  let { active, onsaved, freshness } = $props();

  const res = resource(() => '/api/settings');
  let problem = $state(null);
  let saved = $state(false);
  let savedTimer;

  const s = $derived(res.data);
  const time = $derived(s ? to12Hour(s.recovery_notify_time) : { hour: 7, minute: '30', period: 'AM' });
  const zones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : ['Asia/Kolkata'];
  // Browsers name some zones differently (Chrome lists Asia/Calcutta), so the saved one is always offered.
  const zoneChoices = $derived(s ? [...new Set([s.timezone, ...zones])] : zones);
  const HOURS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
  const MINUTES = ['00', '15', '30', '45'];

  $effect(() => {
    freshness;
    if (active) res.load();
  });

  async function change(values) {
    problem = null;
    try {
      await put('/api/settings', values);
      saved = true;
      clearTimeout(savedTimer);
      savedTimer = setTimeout(() => (saved = false), 1500);
      onsaved?.();
    } catch (failure) {
      problem = failure.message;
    }
    await res.load();
  }

  function heartRate(key, event) {
    const text = event.currentTarget.value.trim();
    change({ [key]: text === '' ? null : Number(text) });
  }

  function clockChange(part, value) {
    const next = { ...time, [part]: value };
    change({ recovery_notify_time: to24Hour(next.hour, next.minute, next.period) });
  }

  const usingEstimate = (key) => s[key] === null;
</script>

<Screen {active}>
  <div class="gutter top">
    <a class="back pressable" href="#/today" aria-label="Back to Today"><Icon name="back" size={22} stroke={2.4} /></a>
    <h1 class="page-heading">Settings</h1>
    <span class="saved" class:show={saved} role="status">{saved ? 'Saved' : ''}</span>
  </div>

  <StatusNote resource={res} what="your settings" />

  {#if problem}
    <div class="gutter"><div class="card attention" role="alert">{problem}</div></div>
  {/if}

  {#if s}
    <section class="gutter stack">
      <h2 class="section-heading">Race</h2>
      <div class="group">
        <div class="row">
          <label for="race-date">Race date</label>
          <input id="race-date" class="field" type="date" value={s.race_date} onchange={(e) => change({ race_date: e.currentTarget.value })} />
        </div>
        <div class="row">
          <label for="zone">Time zone</label>
          <select id="zone" class="field zone" onchange={(e) => change({ timezone: e.currentTarget.value })}>
            {#each zoneChoices as zone (zone)}
              <option value={zone} selected={zone === s.timezone}>{zone.replaceAll('_', ' ')}</option>
            {/each}
          </select>
        </div>
      </div>
      <p class="note">Check this against the official race page. The countdown follows whatever you enter here.</p>
    </section>

    <section class="gutter stack">
      <h2 class="section-heading">Heart rate</h2>
      <div class="group">
        <div class="row-block">
          <div class="row-inner">
            <label for="max-hr">Max HR</label>
            <input id="max-hr" class="field number" type="number" inputmode="numeric" value={s.max_hr ?? ''} placeholder={s.estimates.max_hr === null ? '' : whole(s.estimates.max_hr)} aria-describedby="max-hr-note" onchange={(e) => heartRate('max_hr', e)} />
          </div>
          <p id="max-hr-note" class="note">{usingEstimate('max_hr') ? `${s.estimates.max_hr_source} Enter a number to replace it.` : 'Set by you. Clear it to use the estimate again.'}</p>
        </div>
        <div class="row-block">
          <div class="row-inner">
            <label for="resting-hr">Resting HR</label>
            <input id="resting-hr" class="field number" type="number" inputmode="numeric" value={s.resting_hr ?? ''} placeholder={s.estimates.resting_hr === null ? '' : whole(s.estimates.resting_hr)} aria-describedby="resting-hr-note" onchange={(e) => heartRate('resting_hr', e)} />
          </div>
          <p id="resting-hr-note" class="note">{usingEstimate('resting_hr') ? `${s.estimates.resting_hr_source} Enter a number to replace it.` : 'Set by you. Clear it to use the estimate again.'}</p>
        </div>
      </div>
    </section>

    <section class="gutter stack">
      <h2 class="section-heading">Load curve</h2>
      <div class="card stack">
        <div class="pair" role="group" aria-label="Load curve">
          <button class="choice pressable" aria-pressed={s.trimp_curve === 'male'} onclick={() => change({ trimp_curve: 'male' })}>Men's</button>
          <button class="choice pressable" aria-pressed={s.trimp_curve === 'female'} onclick={() => change({ trimp_curve: 'female' })}>Women's</button>
        </div>
        <p class="note">Strain uses Banister's formula, which weights heart rate differently for men and women. Changing this updates your load straight away.</p>
      </div>
    </section>

    <section class="gutter stack">
      <h2 class="section-heading">Notifications</h2>
      <div class="group">
        <div class="row">
          <span id="n-recovery">Recovery is ready</span>
          <button class="switch" role="switch" aria-labelledby="n-recovery" aria-checked={s.notify_recovery} onclick={() => change({ notify_recovery: !s.notify_recovery })}><i></i></button>
        </div>
        <div class="row">
          <span>Time</span>
          <div class="clock">
            <label class="visually-hidden" for="n-hour">Hour</label>
            <select id="n-hour" class="field" value={time.hour} onchange={(e) => clockChange('hour', e.currentTarget.value)}>
              {#each HOURS as hour (hour)}<option value={hour}>{hour}</option>{/each}
            </select>
            <label class="visually-hidden" for="n-minute">Minute</label>
            <select id="n-minute" class="field" value={time.minute} onchange={(e) => clockChange('minute', e.currentTarget.value)}>
              {#each MINUTES as minute (minute)}<option value={minute}>{minute}</option>{/each}
              {#if !MINUTES.includes(time.minute)}<option value={time.minute}>{time.minute}</option>{/if}
            </select>
            <label class="visually-hidden" for="n-period">AM or PM</label>
            <select id="n-period" class="field" value={time.period} onchange={(e) => clockChange('period', e.currentTarget.value)}>
              <option>AM</option><option>PM</option>
            </select>
          </div>
        </div>
        <div class="row">
          <span id="n-key">Garmin key expiring soon</span>
          <button class="switch" role="switch" aria-labelledby="n-key" aria-checked={s.notify_key_expiring} onclick={() => change({ notify_key_expiring: !s.notify_key_expiring })}><i></i></button>
        </div>
        <div class="row">
          <span id="n-sync">Sync failed</span>
          <button class="switch" role="switch" aria-labelledby="n-sync" aria-checked={s.notify_sync_failed} onclick={() => change({ notify_sync_failed: !s.notify_sync_failed })}><i></i></button>
        </div>
      </div>
      <p class="note">These choices are saved now, but notifications don't send until that part is built.</p>
    </section>

    <section class="gutter stack">
      <h2 class="section-heading">Garmin key</h2>
      <div class="group">
        <div class="row-block">
          <div class="row-inner">
            <label for="key-expiry">Expires on</label>
            <input id="key-expiry" class="field" type="date" value={s.garmin_key_expires ?? ''} aria-describedby="key-note" onchange={(e) => change({ garmin_key_expires: e.currentTarget.value || null })} />
          </div>
          <p id="key-note" class="note">Garmin doesn't share this date with the app, so enter the one from your key page.</p>
        </div>
      </div>
    </section>
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

  .saved {
    margin-left: auto;
    font-size: 12px;
    color: var(--ink-2);
    opacity: 0;
    transition: opacity 0.15s ease;
  }

  .saved.show {
    opacity: 1;
  }

  .group {
    display: flex;
    flex-direction: column;
    border-radius: 8px;
    background: var(--card);
  }

  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    min-height: 52px;
    padding: 4px 12px;
  }

  .row-block {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 12px;
  }

  .row + .row,
  .row-block + .row-block {
    border-top: 1px solid var(--line);
  }

  .row-inner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .zone {
    max-width: 200px;
  }

  .number {
    width: 88px;
    text-align: right;
  }

  .clock {
    display: flex;
    gap: 4px;
  }

  .pair {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 2px;
    padding: 2px;
    border-radius: 8px;
    background: var(--bg);
  }

  .choice {
    height: 44px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--ink-2);
    font: 700 16px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .choice[aria-pressed='true'] {
    background: var(--ink);
    color: var(--bg);
  }

  .switch {
    position: relative;
    flex-shrink: 0;
    width: 52px;
    height: 32px;
    padding: 0;
    border: 0;
    border-radius: 16px;
    background: var(--border);
    transition: background 0.15s ease;
  }

  .switch i {
    position: absolute;
    top: 3px;
    left: 3px;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: var(--ink);
    transition: transform 0.15s ease, background 0.15s ease;
  }

  .switch[aria-checked='true'] {
    background: var(--ink);
  }

  .switch[aria-checked='true'] i {
    transform: translateX(20px);
    background: var(--bg);
  }
</style>
