<script>
  // Auto food targets: fill in your body, your day and your training, see calories, protein, carbs and fat for
  // training days and rest days with how they were worked out, then use them. Each detail saves as you change it.
  import { onMount } from 'svelte';
  import { get } from '../lib/api.js';
  import { ACTIVITY, GOALS, INTENSITY, autoTargets, mergeTargets, missing } from '../lib/autotargets.js';
  import { localDate, targetsFor } from '../lib/food.js';
  import { food as store, loadLibrary, saveSettings, saveTargets, say } from '../lib/food.svelte.js';
  import { whole } from '../lib/format.js';

  const PROTEIN = [1.4, 1.6, 1.8, 2.0, 2.2];
  const LABELS = {
    sex: 'sex',
    birth_year: 'year born',
    height_cm: 'height',
    weight_kg: 'weight',
    activity: 'your day',
    workout_minutes: 'typical workout',
    intensity: 'how hard',
    goal: 'goal',
  };

  let form = $state(null);
  let hint = $state(null);
  let open = $state(false);
  let used = $state(false);

  const library = $derived(store.library);
  const result = $derived(form ? autoTargets(form) : null);
  const gaps = $derived(form ? missing(form) : []);
  const today = localDate();
  const current = $derived({
    training: targetsFor(today, 'training', library?.targets ?? [])?.targets ?? null,
    rest: targetsFor(today, 'rest', library?.targets ?? [])?.targets ?? null,
  });

  onMount(async () => {
    if (!store.library) await loadLibrary();
    try {
      hint = await get('/api/food/training-hint');
    } catch {
      hint = null;
    }
  });

  // The form starts from what was saved, once the library has arrived, with Garmin's typical workout filled in.
  $effect(() => {
    if (form || !library) return;
    const saved = { ...(library.settings?.profile ?? {}) };
    if (saved.workout_minutes === undefined && hint?.minutes) saved.workout_minutes = hint.minutes;
    form = saved;
  });

  // Garmin's suggestion can arrive after the form is ready.
  $effect(() => {
    if (form && hint?.minutes && form.workout_minutes === undefined) form = { ...form, workout_minutes: hint.minutes };
  });

  function set(key, value) {
    form = { ...form, [key]: value };
    used = false;
    const clean = Object.fromEntries(Object.entries(form).filter(([, v]) => v !== undefined && v !== null && v !== ''));
    saveSettings({ profile: clean });
  }

  function setNumber(key, text, whole = false) {
    const value = Number(String(text).trim().replace(',', '.'));
    if (String(text).trim() === '') return set(key, undefined);
    if (!Number.isFinite(value) || (whole && !Number.isInteger(value))) return;
    set(key, value);
  }

  function use() {
    if (!result) return;
    saveTargets('training', today, mergeTargets(current.training, result.training));
    saveTargets('rest', today, mergeTargets(current.rest, result.rest));
    used = true;
    say('Food targets set for training and rest days, from today.');
  }

  const show = (n) => whole(n);
  const now = (kind, key, unit) => (current[kind]?.[key] ? `now ${show(current[kind][key])}${unit}` : 'no target yet');
</script>

<section class="gutter stack">
  <h2 class="section-heading">Food targets</h2>
  {#if !form}
    <p class="note" role="status">{store.libraryError ? store.libraryError.message : 'Loading…'}</p>
  {:else}
    <p class="note">Fill these in and Creed works out daily calories, protein, carbs and fat for training days and rest days. They're estimates to start from.</p>

    <div class="list">
      <div class="list-row">
        <span>Sex</span>
        <div class="pair" role="group" aria-label="Sex">
          <button type="button" class="choice" aria-pressed={form.sex === 'male'} onclick={() => set('sex', 'male')}>Male</button>
          <button type="button" class="choice" aria-pressed={form.sex === 'female'} onclick={() => set('sex', 'female')}>Female</button>
        </div>
      </div>
      <label class="list-row">
        <span>Year born</span>
        <input class="field number" type="text" inputmode="numeric" maxlength="4" placeholder="1995" value={form.birth_year ?? ''} onchange={(e) => setNumber('birth_year', e.currentTarget.value, true)} />
      </label>
      <label class="list-row">
        <span>Height</span>
        <span class="with-unit">
          <input class="field number" type="text" inputmode="decimal" placeholder="175" value={form.height_cm ?? ''} onchange={(e) => setNumber('height_cm', e.currentTarget.value)} />
          <span class="unit">cm</span>
        </span>
      </label>
      <label class="list-row">
        <span>Weight</span>
        <span class="with-unit">
          <input class="field number" type="text" inputmode="decimal" placeholder="70" value={form.weight_kg ?? ''} onchange={(e) => setNumber('weight_kg', e.currentTarget.value)} />
          <span class="unit">kg</span>
        </span>
      </label>
      <label class="list-row">
        <span>Your day</span>
        <select class="field" value={form.activity ?? ''} onchange={(e) => set('activity', e.currentTarget.value || undefined)}>
          <option value="" disabled>Choose</option>
          {#each ACTIVITY as a (a.id)}<option value={a.id}>{a.label}</option>{/each}
        </select>
      </label>
      <label class="list-row">
        <span>Typical workout</span>
        <span class="with-unit">
          <input class="field number" type="text" inputmode="numeric" placeholder="60" value={form.workout_minutes ?? ''} onchange={(e) => setNumber('workout_minutes', e.currentTarget.value, true)} />
          <span class="unit">min</span>
        </span>
      </label>
      <div class="list-row">
        <span>How hard</span>
        <div class="trio" role="group" aria-label="How hard">
          {#each INTENSITY as i (i.id)}
            <button type="button" class="choice" aria-pressed={form.intensity === i.id} onclick={() => set('intensity', i.id)}>{i.label}</button>
          {/each}
        </div>
      </div>
      <label class="list-row">
        <span>Goal</span>
        <select class="field" value={form.goal ?? ''} onchange={(e) => set('goal', e.currentTarget.value || undefined)}>
          <option value="" disabled>Choose</option>
          {#each GOALS as g (g.id)}<option value={g.id}>{g.label}</option>{/each}
        </select>
      </label>
    </div>
    {#if hint?.minutes}
      <p class="note">Your Garmin training days over the last 4 weeks were about {hint.minutes} minutes ({hint.training_days} {hint.training_days === 1 ? 'day' : 'days'}).</p>
    {/if}

    {#if result}
      <div class="results">
        {#each [['training', 'Training day'], ['rest', 'Rest day']] as [kind, title] (kind)}
          {@const r = result[kind]}
          <div class="result">
            <span class="tile-label">{title}</span>
            <span class="kcal">{show(r.kcal)} <small>kcal</small></span>
            <span class="note">{now(kind, 'kcal', ' kcal')}</span>
            <span class="macro protein">{show(r.protein)} g protein</span>
            <span class="macro">{show(r.carbs)} g carbs</span>
            <span class="macro">{show(r.fat)} g fat</span>
          </div>
        {/each}
      </div>

      <button type="button" class="text-button how" aria-expanded={open} onclick={() => (open = !open)}>{open ? 'Hide' : 'How these are worked out'}</button>
      {#if open}
        {@const w = result.workings}
        <div class="card workings">
          <p>Resting burn (Mifflin-St Jeor, age {w.age}): <b>{show(w.resting)} kcal</b></p>
          <p>× {w.factor} for your day: <b>{show(w.daily)} kcal</b>. That's a rest day.</p>
          <p>A {form.workout_minutes}-minute {INTENSITY.find((i) => i.id === form.intensity).label.toLowerCase()} workout adds about ({w.met} − 1) × {form.weight_kg} kg × {form.workout_minutes / 60} h = <b>{show(w.workout)} kcal</b>.</p>
          {#if w.change}<p>Your goal changes both days by <b>{w.change > 0 ? '+' : '−'}{show(Math.abs(w.change))} kcal</b>.</p>{/if}
          <p>Protein {w.proteinPerKg} g per kg. Fat {Math.round(w.fatShare * 100)}% of calories. Carbs are the rest: {result.training.carbsPerKg.toFixed(1)} g per kg on training days, {result.rest.carbsPerKg.toFixed(1)} on rest days.</p>
          {#if result.rest.floored || result.training.floored}<p class="attention">Your goal would take you below your resting burn, so calories stop there.</p>{/if}
          <label class="list-row plain">
            <span>Protein per kg</span>
            <select class="field" value={form.protein_per_kg ?? ''} onchange={(e) => set('protein_per_kg', e.currentTarget.value ? Number(e.currentTarget.value) : undefined)}>
              <option value="">Recommended ({w.change < 0 ? '2.0' : '1.6'})</option>
              {#each PROTEIN as p (p)}<option value={p}>{p} g</option>{/each}
            </select>
          </label>
          <p class="note">Sources: Mifflin-St Jeor (1990); activity factors; workout METs from the Compendium of Physical Activities; protein and carbs from ISSN and ACSM sports nutrition guidance. All are estimates: if your weight moves the wrong way over 2 to 3 weeks, adjust.</p>
        </div>
      {/if}

      <button type="button" class="primary-button pressable" onclick={use}>{used ? 'Targets set' : 'Use these targets'}</button>
      <p class="note">Sets calories, protein, carbs and fat for both day types from today. Other targets, such as sodium, stay as they are, and earlier days keep theirs.</p>
    {:else}
      <p class="note">Still needed: {gaps.map((g) => LABELS[g]).join(', ')}.</p>
    {/if}
  {/if}
</section>

<style>
  .number {
    width: 84px;
    text-align: right;
  }

  .with-unit {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .unit {
    width: 28px;
    font-size: 13px;
    color: var(--ink-3);
  }

  select.field {
    max-width: 210px;
  }

  .pair,
  .trio {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 2px;
    padding: 2px;
    border-radius: 8px;
    background: var(--bg);
  }

  .trio {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .choice {
    height: 40px;
    min-width: 64px;
    padding: 0 8px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--ink-2);
    font: 700 15px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .choice[aria-pressed='true'] {
    background: var(--ink);
    color: var(--bg);
  }

  .results {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .result {
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 12px;
    border-radius: 8px;
    background: var(--card);
  }

  .kcal {
    font: 800 30px/1.05 var(--display);
  }

  .kcal small {
    font-size: 15px;
    color: var(--ink-2);
  }

  .macro {
    font: 700 16px/1.2 var(--display);
  }

  .protein {
    color: var(--protein);
  }

  .how {
    align-self: flex-start;
    margin-left: -4px;
  }

  .workings {
    display: flex;
    flex-direction: column;
    gap: 8px;
    font-size: 13px;
    color: var(--ink-2);
  }

  .workings b {
    color: var(--ink);
    font-weight: 600;
  }

  .plain {
    padding: 0;
  }
</style>
