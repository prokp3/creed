<script>
  // How often a supplement is taken: every day, on certain days of the week, or a number of times a week on any
  // days (once a week is 1). Calls onchange with the new schedule, in the shape the server stores.
  let { schedule = { kind: 'daily' }, onchange, label = 'How often' } = $props();

  const LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
  const NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const KINDS = [
    { kind: 'daily', label: 'Every day' },
    { kind: 'days', label: 'Certain days' },
    { kind: 'weekly', label: 'Times a week' },
  ];

  // Remembered while switching kinds, so going back and forth keeps what you picked.
  let lastDays = $state(schedule.kind === 'days' ? schedule.days : [0, 2, 4]);
  let lastTimes = $state(schedule.kind === 'weekly' ? schedule.times : 1);

  function choose(kind) {
    if (kind === schedule.kind) return;
    if (kind === 'daily') onchange({ kind });
    else if (kind === 'days') onchange({ kind, days: lastDays });
    else onchange({ kind, times: lastTimes });
  }

  function toggleDay(day) {
    const days = schedule.days.includes(day) ? schedule.days.filter((d) => d !== day) : [...schedule.days, day].sort();
    // At least one day; all seven is every day.
    if (!days.length) return;
    lastDays = days;
    onchange(days.length === 7 ? { kind: 'daily' } : { kind: 'days', days });
  }

  function step(by) {
    const times = Math.min(6, Math.max(1, schedule.times + by));
    lastTimes = times;
    onchange({ kind: 'weekly', times });
  }

  const timesText = (n) => ({ 1: 'Once a week', 2: 'Twice a week' })[n] ?? `${n} times a week`;
</script>

<div class="schedule">
  <div class="segments" role="group" aria-label={label}>
    {#each KINDS as k (k.kind)}
      <button type="button" class="segment-button pressable" aria-pressed={schedule.kind === k.kind} onclick={() => choose(k.kind)}>{k.label}</button>
    {/each}
  </div>

  {#if schedule.kind === 'days'}
    <div class="days" role="group" aria-label="Days of the week">
      {#each LETTERS as letter, day (day)}
        <button type="button" class="day pressable" aria-pressed={schedule.days.includes(day)} aria-label={NAMES[day]} onclick={() => toggleDay(day)}>{letter}</button>
      {/each}
    </div>
  {:else if schedule.kind === 'weekly'}
    <div class="times">
      <button type="button" class="step pressable" aria-label="Fewer times a week" disabled={schedule.times <= 1} onclick={() => step(-1)}>−</button>
      <span class="times-text" aria-live="polite">{timesText(schedule.times)}</span>
      <button type="button" class="step pressable" aria-label="More times a week" disabled={schedule.times >= 6} onclick={() => step(1)}>+</button>
    </div>
    <span class="note">Any days, Monday to Sunday. It stays on your list until you've ticked it that many times.</span>
  {/if}
</div>

<style>
  .schedule {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .segments {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(0, 1fr);
    padding: 3px;
    border-radius: 12px;
    background: var(--raised);
  }

  .segment-button {
    min-height: 40px;
    padding: 4px 6px;
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--ink-2);
    font: 800 14px/1.1 var(--display);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .segment-button[aria-pressed='true'] {
    background: var(--ink);
    color: var(--bg);
  }

  .days {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 6px;
  }

  .day {
    height: 40px;
    border: 1px solid var(--border);
    border-radius: 20px;
    background: transparent;
    color: var(--ink-2);
    font: 800 15px/1 var(--display);
  }

  .day[aria-pressed='true'] {
    border-color: var(--ink);
    background: var(--ink);
    color: var(--bg);
  }

  .times {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .step {
    width: 44px;
    height: 40px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: transparent;
    color: var(--ink);
    font: 700 22px/1 var(--display);
  }

  .step:disabled {
    opacity: 0.35;
  }

  .times-text {
    flex: 1;
    font: 700 17px/1 var(--display);
    letter-spacing: 0.04em;
    text-align: center;
    text-transform: uppercase;
  }
</style>
