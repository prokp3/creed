<script>
  // Home screen widget: a read-only key for the Scriptable app, which draws today's food on the home or lock
  // screen. The key is only ever shown inside the script, once, as it's made.
  import { del, get, post } from '../lib/api.js';
  import { shortDate, zonedClock, zonedDate } from '../lib/format.js';
  import { widgetScript } from '../lib/widgetscript.js';

  let { active, freshness, timeZone } = $props();

  const SCRIPTABLE = 'https://apps.apple.com/app/scriptable/id1405459188';

  let status = $state(null);
  let script = $state(null);
  let busy = $state(false);
  let problem = $state(null);
  let copied = $state(false);
  let confirmingNew = $state(false);

  $effect(() => {
    freshness;
    if (active) load();
  });

  async function load() {
    try {
      status = await get('/api/widget/key');
    } catch (failure) {
      problem = failure.message;
    }
  }

  async function attempt(work) {
    busy = true;
    problem = null;
    try {
      await work();
    } catch (failure) {
      problem = failure.message;
    } finally {
      busy = false;
    }
  }

  const turnOn = () =>
    attempt(async () => {
      const result = await post('/api/widget/key');
      script = widgetScript(location.origin, result.key);
      status = { on: result.on, created_at: result.created_at, last_used_at: result.last_used_at };
      confirmingNew = false;
    });

  const turnOff = () =>
    attempt(async () => {
      status = await del('/api/widget/key');
      script = null;
    });

  async function copy() {
    try {
      await navigator.clipboard.writeText(script);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      problem = "Couldn't copy. Select the script below and copy it by hand.";
    }
  }

  function when(iso) {
    const day = zonedDate(iso, timeZone);
    const today = zonedDate(new Date().toISOString(), timeZone);
    return day === today ? `today at ${zonedClock(iso, timeZone)}` : shortDate(day);
  }
</script>

<section class="gutter stack">
  <h2 class="section-heading">Home screen widget</h2>
  <div class="card stack">
    {#if script}
      <p class="note">The widget's ready. This script holds its key and is only shown now, so add it before leaving this screen.</p>
      <ol class="steps">
        <li>Install <a href={SCRIPTABLE} target="_blank" rel="noopener">Scriptable</a> from the App Store. It's free.</li>
        <li>Copy the script below.</li>
        <li>In Scriptable, tap <strong>+</strong>, paste it, and name it <strong>Creed food</strong>.</li>
        <li>Hold down on your home screen, tap <strong>Edit</strong>, then <strong>Add Widget</strong>, and add Scriptable in small or medium. Tap the widget, and choose <strong>Creed food</strong> for Script.</li>
      </ol>
      <button class="primary-button pressable" onclick={copy}>{copied ? 'Copied' : 'Copy script'}</button>
      <textarea class="script" readonly rows="5" aria-label="Widget script">{script}</textarea>
      <p class="note">It works on the lock screen too, as a circle, a rectangle or a line of text. iOS refreshes widgets about every 15 to 30 minutes, and tapping it opens Food.</p>
      <button class="secondary-button pressable" onclick={() => (script = null)}>Done</button>
    {:else if status?.on}
      <p class="note">
        On since {when(status.created_at)}.
        {status.last_used_at ? `The widget last checked in ${when(status.last_used_at)}.` : "The widget hasn't checked in yet."}
      </p>
      {#if confirmingNew}
        <p class="note">A new script stops the old one. Paste the new one into Scriptable afterwards.</p>
        <div class="pair">
          <button class="secondary-button pressable" disabled={busy} onclick={() => (confirmingNew = false)}>Cancel</button>
          <button class="primary-button pressable" disabled={busy} onclick={turnOn}>Make it</button>
        </div>
      {:else}
        <button class="secondary-button pressable" disabled={busy} onclick={() => (confirmingNew = true)}>Make a new script</button>
        <button class="secondary-button pressable" disabled={busy} onclick={turnOff}>Turn off</button>
      {/if}
    {:else if status}
      <p class="note">Shows today's calories and protein against your targets on your home or lock screen, using the free Scriptable app. Its key can only read today's food totals, not your meals, training or settings.</p>
      <button class="primary-button pressable" disabled={busy} onclick={turnOn}>Turn on the widget</button>
    {/if}
    {#if problem}
      <p class="note attention" role="alert">{problem}</p>
    {/if}
  </div>
</section>

<style>
  .steps {
    margin: 0;
    padding-left: 20px;
    color: var(--ink-2);
    font-size: 15px;
    line-height: 1.45;
  }

  .steps li + li {
    margin-top: 6px;
  }

  .steps a {
    color: var(--ink);
  }

  .steps strong {
    color: var(--ink);
  }

  .script {
    width: 100%;
    box-sizing: border-box;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg);
    color: var(--ink-3);
    font: 12px/1.4 ui-monospace, Menlo, monospace;
    resize: none;
  }

  .pair {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
</style>
