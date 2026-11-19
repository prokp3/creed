<script>
  // What you take: add supplements, change a name, dose or how often, remove one. The Food tab then lists the ones
  // due each day to tick off once taken.
  import { tick } from 'svelte';
  import ScheduleField from './ScheduleField.svelte';
  import Sheet from './Sheet.svelte';
  import { newId, scheduleText } from '../lib/food.js';
  import { deleteSupplement, food as store, saveSupplement } from '../lib/food.svelte.js';

  let { onclose } = $props();

  // Names only: a dose depends on the product, so it's never guessed.
  const PICKS = ['Omega-3', 'Vitamin D3', 'Creatine', 'Magnesium', 'Multivitamin', 'Vitamin B12', 'Iron', 'Zinc', 'Electrolytes'];
  const DAILY = { kind: 'daily' };

  let edits = $state({});
  let adding = $state({ name: '', dose: '', schedule: DAILY });
  let open = $state(null);
  let problem = $state('');
  let doseField = $state(null);

  const supplements = $derived(store.library?.supplements ?? []);
  const picks = $derived(PICKS.filter((p) => !supplements.some((s) => s.name.toLowerCase() === p.toLowerCase())));

  const clash = (name, id) => supplements.some((s) => s.id !== id && s.name.toLowerCase() === name.toLowerCase());

  function check(name, dose, id) {
    if (!name || name.length > 40) return 'Give it a name of up to 40 characters.';
    if (dose.length > 40) return 'Keep the dose to 40 characters, such as 1 capsule or 2000 IU.';
    if (clash(name, id)) return `You already have ${name} in your supplements.`;
    return '';
  }

  function save(s, schedule = s.schedule ?? DAILY) {
    const edit = edits[s.id] ?? {};
    const name = (edit.name ?? s.name).trim();
    const dose = (edit.dose ?? s.dose ?? '').trim();
    const sameSchedule = JSON.stringify(schedule) === JSON.stringify(s.schedule ?? DAILY);
    if (name === s.name && dose === (s.dose ?? '') && sameSchedule) return;
    problem = check(name, dose, s.id);
    if (problem) {
      delete edits[s.id];
      return;
    }
    saveSupplement({ id: s.id, name, dose: dose || null, schedule, sort_order: s.sort_order });
  }

  function add() {
    const name = adding.name.trim();
    const dose = adding.dose.trim();
    problem = check(name, dose, null);
    if (problem) return;
    const last = supplements.at(-1)?.sort_order ?? -1;
    saveSupplement({ id: newId(), name, dose: dose || null, schedule: adding.schedule, sort_order: last + 1 });
    adding = { name: '', dose: '', schedule: DAILY };
  }

  async function pick(name) {
    adding.name = name;
    problem = '';
    await tick();
    doseField?.focus();
  }
</script>

<Sheet label="Supplements" {onclose} tall>
  <div class="title-block">
    <h2 class="sheet-title">Supplements</h2>
    <span class="note">What do you take, and how often? Each one shows on the Food tab on the days it's due, to tick off once you've had it.</span>
  </div>

  {#if supplements.length}
    <div class="list">
      {#each supplements as s (s.id)}
        <div class="list-block">
          <div class="fields">
            <input
              class="field name"
              type="text"
              maxlength="40"
              aria-label="Name of {s.name}"
              value={edits[s.id]?.name ?? s.name}
              oninput={(e) => (edits[s.id] = { ...edits[s.id], name: e.currentTarget.value })}
              onchange={() => save(s)}
            />
            <input
              class="field dose"
              type="text"
              maxlength="40"
              placeholder="Dose"
              aria-label="Dose of {s.name}"
              value={edits[s.id]?.dose ?? s.dose ?? ''}
              oninput={(e) => (edits[s.id] = { ...edits[s.id], dose: e.currentTarget.value })}
              onchange={() => save(s)}
            />
          </div>
          <div class="list-inner">
            <button type="button" class="text-button often" aria-expanded={open === s.id} onclick={() => (open = open === s.id ? null : s.id)}>
              {scheduleText(s.schedule)} · {open === s.id ? 'Done' : 'Change'}
            </button>
            <button type="button" class="text-button" aria-label="Remove {s.name}" onclick={() => deleteSupplement(s)}>Remove</button>
          </div>
          {#if open === s.id}
            <ScheduleField schedule={s.schedule ?? DAILY} label="How often you take {s.name}" onchange={(schedule) => save(s, schedule)} />
          {/if}
        </div>
      {/each}
    </div>
  {/if}

  <div class="stack">
    <span class="caption">Add a supplement</span>
    <form class="list list-block adder" onsubmit={(e) => (e.preventDefault(), add())}>
      <div class="fields">
        <input class="field name" type="text" maxlength="40" placeholder="Omega-3" aria-label="New supplement name" bind:value={adding.name} />
        <input class="field dose" type="text" maxlength="40" placeholder="1 capsule" aria-label="New supplement dose (optional)" bind:value={adding.dose} bind:this={doseField} />
      </div>
      <ScheduleField schedule={adding.schedule} label="How often you take it" onchange={(schedule) => (adding.schedule = schedule)} />
      <button type="submit" class="secondary-button pressable add-button">Add</button>
    </form>
    {#if picks.length}
      <div class="picks">
        {#each picks as p (p)}
          <button type="button" class="pick pressable" onclick={() => pick(p)}>{p}</button>
        {/each}
      </div>
    {/if}
    <span class="note">The dose is optional, written your way: 1 capsule, 2000 IU, 5 g.</span>
  </div>
  {#if problem}<p class="note attention" role="alert">{problem}</p>{/if}
</Sheet>

<style>
  .title-block {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding-top: 6px;
  }

  .sheet-title {
    font: 800 26px/1.1 var(--display);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .caption {
    font: 700 13px/1 var(--display);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .list-block {
    gap: 8px;
  }

  .fields {
    display: flex;
    gap: 8px;
  }

  .name {
    flex: 3;
    min-width: 0;
  }

  .dose {
    flex: 2;
    min-width: 0;
  }

  .often {
    margin-left: -4px;
    font-size: 13px;
  }

  .adder {
    gap: 10px;
  }

  .add-button {
    height: 44px;
    font-size: 16px;
  }

  /* Wrapped, not a sideways row. */
  .picks {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .pick {
    height: 36px;
    padding: 0 14px;
    border: 1px solid var(--border);
    border-radius: 18px;
    background: transparent;
    font: 700 14px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
</style>
