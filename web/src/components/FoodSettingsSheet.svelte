<script>
  // Food settings: what makes a training day, reminders to log, and your food log as a CSV file.
  import { onMount } from 'svelte';
  import Sheet from './Sheet.svelte';
  import TimePicker from './TimePicker.svelte';
  import { post } from '../lib/api.js';
  import { clockText } from '../lib/food.js';
  import { food as store, refreshAll, saveSettings, say } from '../lib/food.svelte.js';
  import { isSubscribed, permission, pushSupport, sendTest, startNotifications, stopNotifications } from '../lib/push.js';
  import { pad2 } from '../lib/format.js';

  let { onclose, ontargets } = $props();

  const GAPS = [60, 120, 180, 240, 360];
  const settings = $derived(store.library?.settings);
  const publicKey = $derived(store.library?.push?.public_key ?? null);
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Kolkata';

  let minutesTyped = $state('');
  let newTime = $state(new Date(2000, 0, 1, 13, 0));
  let subscribed = $state(false);
  let busy = $state(false);
  let problem = $state('');
  let preview = $state(null);
  let fileText = $state('');
  let fileName = $state('');
  let replace = $state(false);

  onMount(async () => {
    subscribed = await isSubscribed();
  });

  $effect(() => {
    if (settings && minutesTyped === '') minutesTyped = String(settings.training_minutes);
  });

  function saveMinutes() {
    const value = Number(minutesTyped);
    if (!Number.isInteger(value) || value < 1 || value > 600) {
      problem = 'Use a whole number of minutes from 1 to 600.';
      minutesTyped = String(settings.training_minutes);
      return;
    }
    problem = '';
    if (value !== settings.training_minutes) saveSettings({ training_minutes: value });
  }

  const asText = (t) => {
    const [h, m] = t.split(':').map(Number);
    return clockText(new Date(2000, 0, 1, h, m));
  };

  async function toggleReminders() {
    problem = '';
    if (settings.reminders_on) {
      saveSettings({ reminders_on: false });
      return;
    }
    busy = true;
    try {
      await startNotifications(publicKey);
      subscribed = true;
      saveSettings({ reminders_on: true, timezone: zone, reminder_times: settings.reminder_times.length ? settings.reminder_times : ['13:30', '20:30'] });
    } catch (failure) {
      problem = failure.message;
    } finally {
      busy = false;
    }
  }

  function addTime() {
    const value = `${pad2(newTime.getHours())}:${pad2(newTime.getMinutes())}`;
    if (settings.reminder_times.includes(value)) return;
    if (settings.reminder_times.length >= 8) {
      problem = 'Up to 8 reminder times.';
      return;
    }
    saveSettings({ reminder_times: [...settings.reminder_times, value].sort(), timezone: zone });
  }

  async function test() {
    problem = '';
    busy = true;
    try {
      if (!subscribed) {
        await startNotifications(publicKey);
        subscribed = true;
      }
      await sendTest();
      say('Test sent. It should arrive in a few seconds.');
    } catch (failure) {
      problem = failure.message;
    } finally {
      busy = false;
    }
  }

  async function turnOffHere() {
    await stopNotifications();
    subscribed = false;
  }

  async function exportCsv() {
    problem = '';
    busy = true;
    try {
      const response = await fetch('/api/food/export.csv');
      if (!response.ok) throw new Error(`Couldn't make the file (${response.status}).`);
      const name = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1] ?? 'creed-food.csv';
      const file = new File([await response.blob()], name, { type: 'text/csv' });
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], title: name }).catch(() => {});
      } else {
        const url = URL.createObjectURL(file);
        const link = Object.assign(document.createElement('a'), { href: url, download: name });
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
      }
    } catch (failure) {
      problem = failure.message.includes('fetch') ? "Can't reach Creed. Check your connection." : failure.message;
    } finally {
      busy = false;
    }
  }

  async function chooseFile(event) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (!file) return;
    problem = '';
    preview = null;
    if (file.size > 3_000_000) {
      problem = 'That file is too big. Import up to about 3 MB at a time.';
      return;
    }
    fileText = await file.text();
    fileName = file.name;
    busy = true;
    try {
      preview = await post('/api/food/import/preview', { csv: fileText, timezone: zone });
      replace = false;
    } catch (failure) {
      problem = failure.message;
    } finally {
      busy = false;
    }
  }

  async function runImport() {
    busy = true;
    try {
      const result = await post('/api/food/import', { csv: fileText, timezone: zone, replace_conflicts: replace });
      const saved = (result.counts.new ?? 0) + (result.counts.replaced ?? 0);
      say(`Imported ${saved} ${saved === 1 ? 'entry' : 'entries'}${result.counts.duplicate ? `, skipped ${result.counts.duplicate} already here` : ''}.`);
      preview = null;
      fileText = '';
      refreshAll();
    } catch (failure) {
      problem = failure.message;
    } finally {
      busy = false;
    }
  }

  const supported = pushSupport();
</script>

<Sheet label="Food settings" {onclose} tall>
  <h2 class="sheet-title">Food settings</h2>

  {#if !settings}
    <p class="note" role="status">Loading…</p>
  {:else}
    <section class="stack">
      <h3 class="section-heading">Training days</h3>
      <div class="list">
        <label class="list-row">
          <span>A workout of at least</span>
          <span class="value-input">
            <input class="field number" type="text" inputmode="numeric" aria-label="Minutes" bind:value={minutesTyped} onchange={saveMinutes} />
            <span class="unit-label">min</span>
          </span>
        </label>
        <button type="button" class="list-row link pressable" onclick={ontargets}><span>Targets for training and rest days</span><span class="note">Edit</span></button>
      </div>
      <p class="note">A day with a Garmin workout this long uses training day targets. Others are rest days until a workout syncs, unless you choose.</p>
    </section>

    <section class="stack">
      <h3 class="section-heading">Reminders</h3>
      {#if !publicKey}
        <p class="note">Notifications aren't set up on the server yet. Once the notification keys are added in Vercel, reminders can be turned on here.</p>
      {:else if supported === 'needs-home-screen'}
        <p class="note">Reminders need Creed opened from your home screen (iPhone, iOS 16.4 or later).</p>
      {:else if supported === 'unsupported'}
        <p class="note">This browser can't show notifications.</p>
      {:else}
        <div class="list">
          <label class="list-row">
            <span>Remind me to log</span>
            <input type="checkbox" class="check" checked={settings.reminders_on} disabled={busy} onchange={toggleReminders} />
          </label>
          {#if settings.reminders_on}
            {#each settings.reminder_times as t (t)}
              <div class="list-row">
                <span>{asText(t)}</span>
                <button type="button" class="text-button" aria-label="Remove {asText(t)}" onclick={() => saveSettings({ reminder_times: settings.reminder_times.filter((x) => x !== t) })}>Remove</button>
              </div>
            {/each}
            <div class="list-row">
              <TimePicker bind:value={newTime} label="New reminder time" />
              <button type="button" class="text-button" onclick={addTime}>Add</button>
            </div>
            <label class="list-row">
              <span>Skip if I logged in the last</span>
              <select class="field" value={settings.reminder_gap_minutes} onchange={(e) => saveSettings({ reminder_gap_minutes: Number(e.currentTarget.value) })}>
                {#each GAPS as g (g)}<option value={g}>{g / 60} {g === 60 ? 'hour' : 'hours'}</option>{/each}
              </select>
            </label>
          {/if}
        </div>
        {#if settings.reminders_on}
          <p class="note">
            Reminders arrive within about half an hour of the time, when Creed's schedule next runs, and only if nothing was logged recently. They say nothing about what you ate.
          </p>
          <div class="actions">
            <button type="button" class="secondary-button pressable" disabled={busy} onclick={test}>Send a test</button>
            {#if subscribed}<button type="button" class="secondary-button pressable" disabled={busy} onclick={turnOffHere}>Not on this phone</button>{/if}
          </div>
          {#if permission() === 'denied'}<p class="note">Notifications are blocked for Creed. Allow them in Settings › Notifications › Creed.</p>{/if}
        {/if}
      {/if}
    </section>

    <section class="stack">
      <h3 class="section-heading">Your food log as a file</h3>
      <div class="actions">
        <button type="button" class="secondary-button pressable" disabled={busy} onclick={exportCsv}>Export CSV</button>
        <label class="secondary-button pressable file-button">
          Import CSV
          <input type="file" accept=".csv,text/csv" class="visually-hidden" onchange={chooseFile} disabled={busy} />
        </label>
      </div>
      <p class="note">Export has every entry with its values. Import reads that file back, or a simple one with date, time, food and values. Entries already here are skipped, and nothing is changed without asking.</p>

      {#if preview}
        <div class="card stack">
          <h4 class="tile-label">{fileName}</h4>
          <div class="list">
            <div class="list-row"><span>New entries</span><b>{preview.counts.new}</b></div>
            <div class="list-row"><span>Already here, skipped</span><b>{preview.counts.duplicate}</b></div>
            <div class="list-row"><span>Here but different</span><b>{preview.counts.conflict}</b></div>
            <div class="list-row"><span>Deleted here, skipped</span><b>{preview.counts.deleted}</b></div>
            <div class="list-row"><span>Rows that can't be used</span><b>{preview.error_count}</b></div>
          </div>
          {#if preview.counts.conflict}
            <label class="list-row plain">
              <span>Replace the {preview.counts.conflict} that differ with the file's version</span>
              <input type="checkbox" class="check" bind:checked={replace} />
            </label>
          {/if}
          {#each preview.errors.slice(0, 5) as e (e.row)}<p class="note">Row {e.row}: {e.error}</p>{/each}
          {#if preview.ignored_columns.length}<p class="note">Columns not used: {preview.ignored_columns.join(', ')}.</p>{/if}
          <button type="button" class="primary-button pressable" disabled={busy || !(preview.counts.new || (replace && preview.counts.conflict))} onclick={runImport}>
            Import {preview.counts.new + (replace ? preview.counts.conflict : 0)} entries
          </button>
          <button type="button" class="text-button" onclick={() => (preview = null)}>Cancel</button>
        </div>
      {/if}
    </section>

    {#if problem}<p class="note attention" role="alert">{problem}</p>{/if}
  {/if}
</Sheet>

<style>
  .sheet-title {
    padding-top: 6px;
    font: 800 26px/1.1 var(--display);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .value-input {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .number {
    width: 72px;
    text-align: right;
  }

  .unit-label {
    width: 28px;
    font-size: 13px;
    color: var(--ink-3);
  }

  .link {
    width: 100%;
    border: 0;
    border-top: 1px solid var(--line);
    background: transparent;
    text-align: left;
  }

  .check {
    width: 24px;
    height: 24px;
    accent-color: var(--ink);
  }

  .actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .file-button {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .plain {
    padding: 0;
  }

  .card {
    border-radius: 14px;
  }

  b {
    font-weight: 600;
  }
</style>
