<script>
  // Whether a day uses training or rest targets. Your synced workouts decide unless you choose.
  import Sheet from './Sheet.svelte';
  import { setDayType } from '../lib/food.svelte.js';

  let { date, dayType, isOwner = true, onclose } = $props();

  const choices = $derived([
    { value: null, label: 'Decide from my workouts', note: isOwner ? `Training once a workout of ${dayType.threshold_minutes} minutes or more syncs. Rest until then.` : 'No workouts sync here, so it stays a rest day.' },
    { value: 'training', label: 'Training day', note: 'Use training day targets.' },
    { value: 'rest', label: 'Rest day', note: 'Use rest day targets.' },
  ]);
  const chosen = $derived(dayType.how === 'override' ? dayType.type : null);

  function pick(value) {
    if (value !== chosen) setDayType(date, value);
    onclose();
  }
</script>

<Sheet label="Day type" {onclose}>
  <h2 class="sheet-title">Day type</h2>
  <div class="list">
    {#each choices as choice (choice.label)}
      <button type="button" class="list-row choice pressable" aria-pressed={choice.value === chosen} onclick={() => pick(choice.value)}>
        <span class="choice-text">
          <span class="choice-name">{choice.label}</span>
          <span class="note">{choice.note}</span>
        </span>
        <span class="tick" aria-hidden="true">{choice.value === chosen ? '✓' : ''}</span>
      </button>
    {/each}
  </div>
</Sheet>

<style>
  .sheet-title {
    padding-top: 6px;
    font: 800 26px/1.1 var(--display);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .choice {
    width: 100%;
    border: 0;
    background: transparent;
    text-align: left;
  }

  .list .choice + .choice {
    border-top: 1px solid var(--line);
  }

  .choice-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 0;
  }

  .choice-name {
    font-size: 15px;
    font-weight: 600;
  }

  .tick {
    flex: none;
    width: 20px;
    font-size: 18px;
    font-weight: 700;
  }
</style>
