<script>
  // The Food tab: rings for calories and protein, the other nutrients, presets to log a meal in one tap, and the
  // day's meals. Everything changes on screen the moment you tap; the server catches up behind it.
  import { untrack } from 'svelte';
  import AddFoodSheet from '../components/AddFoodSheet.svelte';
  import DayTypeSheet from '../components/DayTypeSheet.svelte';
  import FoodRing from '../components/FoodRing.svelte';
  import Icon from '../components/Icon.svelte';
  import MealSheet from '../components/MealSheet.svelte';
  import NutrientSheet from '../components/NutrientSheet.svelte';
  import PresetsSheet from '../components/PresetsSheet.svelte';
  import Screen from '../components/Screen.svelte';
  import TargetsSheet from '../components/TargetsSheet.svelte';
  import { addDays, amountText, at, clockText, localDate, mealSummary } from '../lib/food.js';
  import { dayView, food as store, loadDay, loadLibrary, logPreset } from '../lib/food.svelte.js';
  import { relativeDay } from '../lib/format.js';

  // `open` comes from the address, such as #/food/protein from a ring on Today.
  let { active, freshness, open = null } = $props();

  let date = $state(localDate());
  let sheet = $state(null);

  const today = $derived(localDate());
  const view = $derived(dayView(date));
  const library = $derived(store.library);
  const presets = $derived(library?.presets ?? []);
  const rings = $derived(view.loaded ? view.progress.filter((p) => p.id === 'kcal' || p.id === 'protein') : []);
  const bars = $derived(view.loaded ? view.progress.filter((p) => p.id !== 'kcal' && p.id !== 'protein') : []);
  const anyIncomplete = $derived(view.loaded && view.progress.some((p) => p.incomplete));
  const openMeal = $derived(sheet?.kind === 'meal' && view.loaded ? view.meals.find((m) => m.group_id === sheet.groupId) : null);
  const openNutrient = $derived(sheet?.kind === 'nutrient' && view.loaded ? view.progress.find((p) => p.id === sheet.id) : null);

  $effect(() => {
    freshness;
    if (!active) return;
    const day = date;
    // Loading reads the store, which mustn't make this run again when the data arrives.
    untrack(() => {
      loadDay(day);
      loadLibrary();
    });
  });

  // Coming back after midnight moves you on to the new day, unless you were looking at another one.
  let lastToday = localDate();
  $effect(() => {
    freshness;
    const now = localDate();
    if (now !== lastToday && date === lastToday) date = now;
    lastToday = now;
  });

  $effect(() => {
    if (!open) return;
    sheet = open === 'add' ? { kind: 'add' } : { kind: 'nutrient', id: open };
  });

  function close() {
    sheet = null;
    if (open) location.hash = '#/food';
  }

  // A meal logged on a past day goes at this time of day on that day.
  function whenFor(day) {
    const now = new Date();
    return day === localDate(now) ? now : at(day, now.getHours(), now.getMinutes());
  }

  const dayTypeNote = $derived.by(() => {
    if (!view.loaded) return '';
    if (view.dayType.how === 'override') return 'Set by you';
    if (view.dayType.how === 'garmin') return 'Workout synced from Garmin';
    return view.isToday ? 'Until a workout syncs' : 'No workout synced';
  });

  // Eaten minus burned: + is a surplus, − a deficit. Neither is a problem, so neither is red.
  const netText = (value) => (Math.round(value) === 0 ? '0' : `${value > 0 ? '+' : '−'}${amountText(Math.abs(value), 'kcal')}`);
  const colorOf = (id) => (id === 'protein' ? 'var(--protein)' : 'var(--ink)');
  const kcal = (values) => (values.kcal === undefined ? '—' : `${amountText(values.kcal, 'kcal')} kcal`);
</script>

<Screen {active}>
  {#snippet overlay()}
    <button type="button" class="add pressable" aria-label="Add food" onclick={() => (sheet = { kind: 'add' })}>
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
    </button>
  {/snippet}

  <div class="top gutter">
    <h1 class="page-heading">Food</h1>
    <div class="day-nav">
      <button type="button" class="nav-button pressable" aria-label="Previous day" onclick={() => (date = addDays(date, -1))}><Icon name="back" size={20} stroke={2.2} /></button>
      <span class="day-name" aria-live="polite">{relativeDay(date, today)}</span>
      <button type="button" class="nav-button pressable" aria-label="Next day" disabled={date >= today} onclick={() => (date = addDays(date, 1))}><Icon name="forward" size={20} stroke={2.2} /></button>
    </div>
  </div>

  {#if !view.loaded}
    <div class="gutter">
      {#if view.error}
        <div class="card note" role="alert">{view.error.message}</div>
      {:else}
        <p class="note" role="status">Loading…</p>
      {/if}
    </div>
  {:else}
    {#if view.error}
      <div class="gutter"><div class="card note" role="alert">{view.error.message} You're seeing the last numbers that loaded.</div></div>
    {/if}

    <div class="day-type gutter">
      <span class="day-type-name">{view.dayType.type === 'training' ? 'Training day' : 'Rest day'}</span>
      <span class="day-type-note">· {dayTypeNote}</span>
      <button type="button" class="text-button change" onclick={() => (sheet = { kind: 'day-type' })}>Change</button>
    </div>

    <div class="rings gutter">
      {#each rings as item (item.id)}
        <FoodRing {item} color={colorOf(item.id)} onclick={() => (sheet = { kind: 'nutrient', id: item.id })} />
      {/each}
    </div>
    {#if !view.targetSet}
      <div class="gutter">
        <button type="button" class="secondary-button pressable" onclick={() => (sheet = { kind: 'targets' })}>Set {view.dayType.type} day targets</button>
      </div>
    {/if}

    <div class="gutter">
      <div class="bars">
        {#each bars as item (item.id)}
          <button type="button" class="bar-row pressable" onclick={() => (sheet = { kind: 'nutrient', id: item.id })} aria-label="{item.name} {amountText(item.eaten, item.unit)}{item.target === null ? '' : ` of ${amountText(item.target, item.unit)}`} {item.unit}">
            <span class="bar-name">{item.name}</span>
            <span class="bar-track"><span class="bar-fill" style:width="{Math.min(1, item.fraction) * 100}%"></span></span>
            <span class="bar-value">
              {amountText(item.eaten, item.unit)}{item.incomplete ? '*' : ''}{item.target === null ? '' : ` / ${amountText(item.target, item.unit)}`} {item.unit}
            </span>
          </button>
        {/each}
        {#if anyIncomplete}
          <p class="note">* May be low: some foods logged don't list it.</p>
        {/if}
        {#if view.targetSet}
          <button type="button" class="text-button targets-link" onclick={() => (sheet = { kind: 'targets' })}>Edit targets</button>
        {/if}
      </div>
    </div>

    {#if view.balance.burned_kcal !== null}
      <div class="gutter">
        <div class="balance">
          <span class="figure"><span class="caption">Eaten</span><span class="figure-value">{amountText(view.balance.eaten_kcal, 'kcal')}</span></span>
          <span class="figure">
            <span class="caption">{view.balance.so_far ? 'Burned so far' : 'Burned'}</span>
            <span class="figure-value">{amountText(view.balance.burned_kcal, 'kcal')}</span>
          </span>
          <span class="figure"><span class="caption">Net</span><span class="figure-value">{netText(view.balance.net_kcal)}</span></span>
          <span class="tag balance-tag">KCAL · BURN FROM GARMIN, AN ESTIMATE{view.balance.so_far ? ' · TODAY ISN’T OVER' : ''}</span>
        </div>
      </div>
    {/if}

    <section class="stack">
      <div class="section-top gutter">
        <h2 class="section-heading">Presets</h2>
        {#if presets.length}
          <button type="button" class="text-button" onclick={() => (sheet = { kind: 'presets' })}>Edit</button>
        {/if}
      </div>
      {#if presets.length}
        <div class="chips">
          {#each presets as preset (preset.id)}
            <button type="button" class="chip pressable" onclick={() => logPreset(preset, whenFor(date))}>{preset.name}</button>
          {/each}
        </div>
      {:else}
        <p class="note gutter">No presets yet. Log a meal, tap it, then choose Save as a preset to log it again in one tap.</p>
      {/if}
    </section>

    <section class="gutter stack meals-section">
      <h2 class="section-heading">{view.isToday ? "Today's meals" : 'Meals'}</h2>
      {#if view.meals.length}
        <div class="list">
          {#each view.meals as meal (meal.group_id)}
            <button type="button" class="meal pressable" onclick={() => (sheet = { kind: 'meal', groupId: meal.group_id })}>
              <span class="meal-text">
                <span class="meal-name">{meal.label}</span>
                <span class="meal-note">{clockText(new Date(meal.logged_at))} · {mealSummary(meal)}</span>
              </span>
              <span class="meal-values">
                <span class="meal-kcal">{kcal(meal.totals)}</span>
                {#if meal.totals.protein !== undefined}<span class="meal-protein">{amountText(meal.totals.protein, 'g')} g protein</span>{/if}
              </span>
            </button>
          {/each}
        </div>
      {:else}
        <p class="note">Nothing logged {view.isToday ? 'yet today' : 'on this day'}. Tap + to add food.</p>
      {/if}
    </section>
  {/if}
</Screen>

{#if sheet?.kind === 'add'}
  <AddFoodSheet {date} onclose={close} />
{:else if openMeal}
  <MealSheet meal={openMeal} nutrients={library?.nutrients ?? []} onclose={close} />
{:else if openNutrient}
  <NutrientSheet item={openNutrient} entries={view.entries} color={colorOf(openNutrient.id)} onclose={close} onsettargets={() => (sheet = { kind: 'targets' })} />
{:else if sheet?.kind === 'targets'}
  <TargetsSheet initialType={view.loaded ? view.dayType.type : 'training'} onclose={close} />
{:else if sheet?.kind === 'day-type' && view.loaded}
  <DayTypeSheet {date} dayType={view.dayType} onclose={close} />
{:else if sheet?.kind === 'presets'}
  <PresetsSheet onclose={close} />
{/if}

<style>
  .top {
    display: flex;
    align-items: center;
    gap: 4px;
    min-height: 44px;
  }

  .day-nav {
    display: flex;
    align-items: center;
    margin-left: auto;
    margin-right: -12px;
  }

  .nav-button {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    border: 0;
    background: transparent;
    color: var(--ink-2);
  }

  .nav-button:disabled {
    color: var(--track);
  }

  .day-name {
    min-width: 78px;
    font: 700 16px/1 var(--display);
    letter-spacing: 0.06em;
    text-align: center;
    text-transform: uppercase;
  }

  .day-type {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: -8px;
  }

  .day-type-name {
    font: 700 13px/1 var(--display);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-2);
  }

  .day-type-note {
    font-size: 12px;
    color: var(--ink-3);
  }

  .change {
    margin-left: auto;
    font-size: 13px;
  }

  .rings {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .bars {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 14px;
    border-radius: 14px;
    background: var(--card);
  }

  .bar-row {
    display: grid;
    grid-template-columns: 84px minmax(0, 1fr) 118px;
    align-items: center;
    gap: 10px;
    min-height: 32px;
    padding: 0;
    border: 0;
    background: transparent;
    text-align: left;
  }

  .bar-name {
    font: 700 14px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--ink-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .bar-track {
    display: flex;
    height: 6px;
    border-radius: 3px;
    background: var(--track);
    overflow: hidden;
  }

  .bar-fill {
    border-radius: 3px;
    background: var(--ink);
    transition: width 0.4s var(--ease);
  }

  .bar-value {
    font-size: 13px;
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  .targets-link {
    align-self: flex-start;
    margin-left: -4px;
    font-size: 13px;
  }

  .balance {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px 8px;
    padding: 12px 14px;
    border-radius: 14px;
    background: var(--card);
  }

  .figure {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .caption {
    font: 700 12px/1 var(--display);
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .figure-value {
    font: 800 24px/1 var(--display);
  }

  .balance-tag {
    grid-column: 1 / -1;
  }

  .section-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 32px;
  }

  .section-top .text-button {
    min-height: 32px;
  }

  /* Presets in a row you can swipe sideways: the owner's pick (layout A) over the no-sideways-scrolling rule. */
  .chips {
    display: flex;
    gap: 8px;
    padding: 0 var(--gutter);
    overflow-x: auto;
    overscroll-behavior-x: contain;
    scrollbar-width: none;
    scroll-padding: 0 var(--gutter);
  }

  .chips::-webkit-scrollbar {
    display: none;
  }

  .chip {
    flex-shrink: 0;
    height: 48px;
    padding: 0 18px;
    border: 1px solid var(--border);
    border-radius: 24px;
    background: transparent;
    font: 700 16px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
    white-space: nowrap;
  }

  /* Room under the last meal so the add button never covers it. */
  .meals-section {
    padding-bottom: 72px;
  }

  .meal {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    min-height: 64px;
    padding: 8px 14px;
    border: 0;
    background: transparent;
    text-align: left;
  }

  .meal + .meal {
    border-top: 1px solid var(--line);
  }

  .meal-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
  }

  .meal-name {
    font: 700 17px/1.1 var(--display);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .meal-note {
    overflow: hidden;
    font-size: 12px;
    color: var(--ink-3);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .meal-values {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
    flex: none;
  }

  .meal-kcal {
    font: 800 18px/1 var(--display);
  }

  .meal-protein {
    font-size: 12px;
    color: var(--protein);
  }

  .add {
    position: absolute;
    z-index: 2;
    right: var(--gutter);
    bottom: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 60px;
    height: 60px;
    border: 0;
    border-radius: 30px;
    background: var(--ink);
    color: var(--bg);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  }
</style>
