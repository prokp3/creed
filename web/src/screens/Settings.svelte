<script>
  // Each change saves on its own, the way a phone's settings do. There's no Save button.
  import Icon from '../components/Icon.svelte';
  import Screen from '../components/Screen.svelte';
  import SignInSettings from '../components/SignInSettings.svelte';
  import StatusNote from '../components/StatusNote.svelte';
  import { onMount } from 'svelte';
  import { put } from '../lib/api.js';
  import { to12Hour, to24Hour, whole } from '../lib/format.js';
  import { isSubscribed, permission, pushSupport, sendTest, startNotifications, stopNotifications } from '../lib/push.js';
  import { resource } from '../lib/resource.svelte.js';

  let { active, onsaved, freshness } = $props();

  const res = resource(() => '/api/settings');
  let problem = $state(null);
  let saved = $state(false);
  let savedTimer;

  const s = $derived(res.data);
  // Only a Garmin key expires. intervals.icu keys don't, and with no watch there's no key at all.
  const sourceKey = $derived(s?.data_source?.key ?? 'garmin');
  const intervals = $derived(sourceKey !== 'garmin');
  const supported = pushSupport();
  let subscribed = $state(false);
  let pushBusy = $state(false);
  let tested = $state('');

  onMount(async () => {
    subscribed = await isSubscribed();
  });
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

  function clockChange(key, part, value) {
    const next = { ...to12Hour(s[key]), [part]: value };
    change({ [key]: to24Hour(next.hour, next.minute, next.period) });
  }

  // Notifications on this phone. iOS asks permission once, after this tap.
  async function togglePhone() {
    problem = null;
    tested = '';
    pushBusy = true;
    try {
      if (subscribed) {
        await stopNotifications();
        subscribed = false;
      } else {
        await startNotifications(s.push.public_key);
        subscribed = true;
      }
    } catch (failure) {
      problem = failure.message;
    } finally {
      pushBusy = false;
    }
    await res.load();
  }

  async function test() {
    problem = null;
    tested = '';
    pushBusy = true;
    try {
      await sendTest('settings');
      tested = 'Sent. It should arrive in a few seconds.';
    } catch (failure) {
      problem = failure.message;
    } finally {
      pushBusy = false;
    }
  }

  const usingEstimate = (key) => s[key] === null;
</script>

{#snippet toggle(key, label)}
  <div class="list-row">
    <span id="n-{key}">{label}</span>
    <button class="switch" role="switch" aria-labelledby="n-{key}" aria-checked={s[key]} onclick={() => change({ [key]: !s[key] })}><i></i></button>
  </div>
{/snippet}

{#snippet clock(key, label)}
  {@const time = to12Hour(s[key])}
  <div class="list-row">
    <span>Time</span>
    <div class="clock">
      <label class="visually-hidden" for="{key}-hour">{label} hour</label>
      <select id="{key}-hour" class="field" value={time.hour} onchange={(e) => clockChange(key, 'hour', e.currentTarget.value)}>
        {#each HOURS as hour (hour)}<option value={hour}>{hour}</option>{/each}
      </select>
      <label class="visually-hidden" for="{key}-minute">{label} minute</label>
      <select id="{key}-minute" class="field" value={time.minute} onchange={(e) => clockChange(key, 'minute', e.currentTarget.value)}>
        {#each MINUTES as minute (minute)}<option value={minute}>{minute}</option>{/each}
        {#if !MINUTES.includes(time.minute)}<option value={time.minute}>{time.minute}</option>{/if}
      </select>
      <label class="visually-hidden" for="{key}-period">{label} AM or PM</label>
      <select id="{key}-period" class="field" value={time.period} onchange={(e) => clockChange(key, 'period', e.currentTarget.value)}>
        <option>AM</option><option>PM</option>
      </select>
    </div>
  </div>
{/snippet}

<Screen {active}>
  <div class="gutter top">
    <a class="back pressable" href="#/today" aria-label="Back to Today"><Icon name="back" size={22} stroke={2.4} /></a>
    <h1 class="page-heading">Settings</h1>
    <span class="saved" class:show={saved} role="status">{saved ? 'Saved' : ''}</span>
  </div>

  <StatusNote resource={res} />

  {#if problem}
    <div class="gutter"><div class="card attention" role="alert">{problem}</div></div>
  {/if}

  {#if s}
    <section class="gutter stack">
      <h2 class="section-heading">Race</h2>
      <div class="list">
        <div class="list-row">
          <label for="race-date">Race date</label>
          <input id="race-date" class="field" type="date" value={s.race_date} onchange={(e) => change({ race_date: e.currentTarget.value })} />
        </div>
        <div class="list-row">
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
      <div class="list">
        <div class="list-block">
          <div class="list-inner">
            <label for="max-hr">Max HR</label>
            <input id="max-hr" class="field number" type="number" inputmode="numeric" value={s.max_hr ?? ''} placeholder={s.estimates.max_hr === null ? '' : whole(s.estimates.max_hr)} aria-describedby="max-hr-note" onchange={(e) => heartRate('max_hr', e)} />
          </div>
          <p id="max-hr-note" class="note">{usingEstimate('max_hr') ? `${s.estimates.max_hr_source} Enter a number to replace it.` : 'Set by you. Clear it to use the estimate again.'}</p>
        </div>
        <div class="list-block">
          <div class="list-inner">
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
      {#if !s.push.public_key}
        <p class="note">Notifications aren't set up on the server yet. Once the notification keys are added in Vercel, you can turn them on here. Your choices below are saved now.</p>
      {:else if supported === 'needs-home-screen'}
        <p class="note">Notifications need Creed opened from your home screen (iPhone, iOS 16.4 or later). Your choices below are saved now.</p>
      {:else if supported === 'unsupported'}
        <p class="note">This browser can't show notifications.</p>
      {:else}
        <div class="list">
          <div class="list-row">
            <span id="n-phone">On this phone</span>
            <button class="switch" role="switch" aria-labelledby="n-phone" aria-checked={subscribed} disabled={pushBusy} data-no-haptics onclick={togglePhone}><i></i></button>
          </div>
        </div>
        {#if permission() === 'denied'}<p class="note">Notifications are blocked for Creed. Allow them in Settings › Notifications › Creed.</p>{/if}
        {#if subscribed}
          <div class="actions">
            <button type="button" class="secondary-button pressable" disabled={pushBusy} onclick={test}>Send a test</button>
          </div>
          {#if tested}<p class="note" role="status">{tested}</p>{/if}
        {:else if s.push.phones > 0}
          <p class="note">Notifications go to {s.push.phones === 1 ? 'one other phone or browser' : `${s.push.phones} other phones or browsers`}.</p>
        {/if}
      {/if}
      <div class="list">
        {@render toggle('notify_recovery', 'Recovery is ready')}
        {#if s.notify_recovery}{@render clock('recovery_notify_time', 'Recovery')}{/if}
        {@render toggle('notify_workout', 'Workout recaps')}
        {@render toggle('notify_load_spike', 'Load spike warning')}
        {@render toggle('notify_weekly', 'Weekly summary on Sundays')}
        {#if s.notify_weekly}{@render clock('weekly_notify_time', 'Weekly summary')}{/if}
        {#if !intervals}{@render toggle('notify_key_expiring', 'Garmin key expiring soon')}{/if}
        {@render toggle('notify_sync_failed', 'Sync failed')}
      </div>
      <p class="note">Creed checks about every 30 minutes, so notifications can be up to half an hour late. Recovery waits for last night's HRV, and is skipped if there's no score within 3 hours of your time. A load spike means your last week's load is at least 1.5 times your six-week average. Apart from Recovery and the weekly summary, nothing is sent between 10 PM and 7 AM.</p>
      <p class="note">Recaps and summaries include your numbers. To hide them on the lock screen, set iPhone Settings › Notifications › Show Previews to When Unlocked.</p>
    </section>

    {#if intervals}
      <section class="gutter stack">
        <h2 class="section-heading">Data source</h2>
        <div class="list">
          <div class="list-block">
            <div class="list-inner">
              <span>Synced from</span>
              <span class="note">{s.data_source.label}</span>
            </div>
            {#if sourceKey === 'none'}
              <p class="note">No watch is connected, so nothing syncs. The race countdown, food logging, targets and reminders all work. To add a watch later, set CREED_DATA_SOURCE to garmin or intervals in Vercel and add its key.</p>
            {:else}
              <p class="note">Creed reads your watch's data from intervals.icu with your API key, which doesn't expire. Body Battery, stress and Garmin's training effects are Garmin's own, so they don't appear.</p>
            {/if}
          </div>
        </div>
      </section>
    {:else}
      <section class="gutter stack">
        <h2 class="section-heading">Garmin key</h2>
        <div class="list">
          <div class="list-block">
            <div class="list-inner">
              <label for="key-expiry">Expires on</label>
              <input id="key-expiry" class="field" type="date" value={s.garmin_key_expires ?? ''} aria-describedby="key-note" onchange={(e) => change({ garmin_key_expires: e.currentTarget.value || null })} />
            </div>
            <p id="key-note" class="note">Garmin doesn't share this date with the app, so enter the one from your key page.</p>
          </div>
        </div>
      </section>
    {/if}

    <SignInSettings {active} {freshness} timeZone={s.timezone} />
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

  .zone {
    max-width: 200px;
  }

  .number {
    width: 88px;
    text-align: right;
  }

  .actions {
    display: flex;
    gap: 8px;
  }

  .switch:disabled {
    opacity: 0.5;
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
