<script>
  // Adding food: search the library (favourites and recent ones first), pick an amount, log it. Or add something
  // eaten once by typing its values.
  import Icon from './Icon.svelte';
  import QuantityPanel from './QuantityPanel.svelte';
  import Sheet from './Sheet.svelte';
  import TimePicker from './TimePicker.svelte';
  import {
    amountText,
    at,
    entryFromFood,
    localDate,
    number,
    oneOffEntry,
    quantityText,
    scale,
    searchFoods,
    startingQuantity,
    unitAmount,
    unitChoices,
  } from '../lib/food.js';
  import { food as store, logEntries, toggleFavourite } from '../lib/food.svelte.js';
  import { warmUp } from '../lib/scanner.js';
  import { onMount, untrack } from 'svelte';

  const SHOW_AT_MOST = 80;

  // `startWith`: a food to go straight to, such as one just scanned or made.
  let { date, onclose, onscan, onnewfood, startWith = null } = $props();

  function startTime() {
    const now = new Date();
    return date === localDate(now) ? now : at(date, now.getHours(), now.getMinutes());
  }

  let step = $state(untrack(() => (startWith ? 'food' : 'search')));
  let query = $state('');
  let chosenId = $state(untrack(() => startWith?.id ?? null));
  let quantity = $state(untrack(() => (startWith ? startingQuantity(startWith.default_unit, startWith.base) : 1)));
  let unit = $state(untrack(() => startWith?.default_unit ?? 'g'));
  let when = $state(startTime());
  let oneOffName = $state('');
  let oneOffValues = $state({});

  const library = $derived(store.library);
  const nutrients = $derived(library?.nutrients ?? []);
  const foods = $derived(library?.foods ?? []);
  // A food made a moment ago may still be on its way to the server, so it can come from `startWith` too.
  const chosen = $derived(foods.find((f) => f.id === chosenId) ?? (startWith?.id === chosenId ? startWith : null));
  const picks = $derived(searchFoods(foods, query, library?.recent_food_ids ?? []));
  const everything = $derived(query.trim() ? [] : [...foods].sort((a, b) => a.name.localeCompare(b.name)));
  const quantityValid = $derived(Number.isFinite(quantity) && quantity > 0 && quantity <= 100000);

  // The barcode reader takes a moment to load, so start before it's needed.
  onMount(warmUp);

  function choose(item) {
    chosenId = item.id;
    unit = item.default_unit;
    quantity = startingQuantity(unit, item.base);
    step = 'food';
  }

  function perUnit(item) {
    const amount = item.default_unit === item.base ? 100 : unitAmount(item.default_unit, item.base, item.units);
    const values = scale(item.nutrients, amount);
    const kcal = values.kcal === undefined ? '' : `${amountText(values.kcal, 'kcal')} kcal`;
    const protein = values.protein === undefined ? '' : `${amountText(values.protein, 'g')} g protein`;
    const per = item.default_unit === item.base ? `100 ${item.base}` : `${item.default_unit} (${number(amount)} ${item.base})`;
    const text = [kcal, protein].filter(Boolean).join(' · ');
    return text ? `${text} per ${per}` : `No calories or protein listed`;
  }

  function logChosen() {
    if (!chosen || !quantityValid) return;
    const entry = entryFromFood(chosen, { quantity, unit, when });
    logEntries([entry], `${chosen.name} logged · ${quantityText(quantity, unit)}`);
    onclose();
  }

  function readValue(id, event) {
    const text = event.currentTarget.value.trim().replace(',', '.');
    const parsed = Number(text);
    oneOffValues = { ...oneOffValues, [id]: text && Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined };
  }

  const oneOffValid = $derived(
    oneOffName.trim().length > 0 && Object.values(oneOffValues).some((v) => Number.isFinite(v)),
  );

  function logOneOff() {
    if (!oneOffValid) return;
    const values = Object.fromEntries(Object.entries(oneOffValues).filter(([, v]) => Number.isFinite(v)));
    logEntries([oneOffEntry({ name: oneOffName.trim().slice(0, 80), values, when })], `${oneOffName.trim()} logged`);
    onclose();
  }
</script>

<Sheet label="Add food" {onclose} tall>
  {#if step === 'search'}
    <div class="head">
      <h2 class="sheet-title">Add food</h2>
    </div>
    <input class="field search" type="search" placeholder="Search your foods" aria-label="Search your foods" bind:value={query} autocomplete="off" />
    <div class="actions">
      <button type="button" class="secondary-button pressable" onclick={onscan}>Scan a barcode</button>
      <button type="button" class="secondary-button pressable" onclick={() => (step = 'one-off')}>Quick add once</button>
    </div>

    {#if !library}
      <p class="note" role="status">{store.libraryError ? store.libraryError.message : 'Loading your foods…'}</p>
    {:else}
      {#if picks.length}
        <section class="stack">
          <h3 class="section-heading">{query.trim() ? 'Matches' : 'Favourites and recent'}</h3>
          <div class="list">
            {#each picks.slice(0, SHOW_AT_MOST) as item (item.id)}
              <button type="button" class="list-row food-row pressable" onclick={() => choose(item)}>
                <span class="food-text">
                  <span class="food-name">{item.name}{item.favourite ? ' ★' : ''}</span>
                  <span class="note">{item.brand ? `${item.brand} · ` : ''}{perUnit(item)}</span>
                </span>
                <Icon name="forward" size={18} />
              </button>
            {/each}
          </div>
        </section>
      {:else if query.trim()}
        <p class="note">No food called “{query.trim()}” yet.</p>
        <button type="button" class="secondary-button pressable" onclick={() => onnewfood(query.trim())}>Add “{query.trim()}” to your foods</button>
      {/if}
      {#if everything.length}
        <section class="stack">
          <h3 class="section-heading">All foods</h3>
          <div class="list">
            {#each everything.slice(0, SHOW_AT_MOST) as item (item.id)}
              <button type="button" class="list-row food-row pressable" onclick={() => choose(item)}>
                <span class="food-text">
                  <span class="food-name">{item.name}</span>
                  <span class="note">{perUnit(item)}</span>
                </span>
                <Icon name="forward" size={18} />
              </button>
            {/each}
          </div>
          {#if everything.length > SHOW_AT_MOST}<p class="note">Search to find the other {everything.length - SHOW_AT_MOST}.</p>{/if}
        </section>
      {/if}
    {/if}
  {:else if step === 'food' && chosen}
    <div class="head">
      <button type="button" class="icon-button pressable" aria-label="Back to search" onclick={() => (step = 'search')}><Icon name="back" size={22} stroke={2.4} /></button>
      <div class="title-block">
        <h2 class="sheet-title">{chosen.name}</h2>
        <span class="note">
          {chosen.brand ? `${chosen.brand} · ` : ''}Per 100 {chosen.base}: {chosen.nutrients.kcal === undefined ? 'kcal not listed' : `${amountText(chosen.nutrients.kcal, 'kcal')} kcal`} · {chosen.nutrients.protein === undefined ? 'protein not listed' : `${number(chosen.nutrients.protein)} g protein`}{chosen.source === 'seed' ? ' · Typical values' : ''}
        </span>
      </div>
      <button type="button" class="icon-button pressable" aria-label={chosen.favourite ? 'Remove from favourites' : 'Add to favourites'} aria-pressed={chosen.favourite} onclick={() => toggleFavourite(chosen.id)}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill={chosen.favourite ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2l1.1-6.2L3 9.6l6.2-.9z" /></svg>
      </button>
    </div>

    <QuantityPanel base={chosen.base} units={chosen.units} unitOptions={unitChoices(chosen)} per100={chosen.nutrients} {nutrients} bind:quantity bind:unit />

    <div class="time-row">
      <span class="caption">Time</span>
      <TimePicker bind:value={when} />
    </div>

    <button type="button" class="primary-button big pressable" disabled={!quantityValid} onclick={logChosen}>
      {quantityValid ? `Log ${quantityText(quantity, unit)}` : 'Enter a quantity'}
    </button>
  {:else if step === 'one-off'}
    <div class="head">
      <button type="button" class="icon-button pressable" aria-label="Back to search" onclick={() => (step = 'search')}><Icon name="back" size={22} stroke={2.4} /></button>
      <div class="title-block">
        <h2 class="sheet-title">Quick add</h2>
        <span class="note">For something eaten once. It isn't added to your library.</span>
      </div>
    </div>

    <label class="stack">
      <span class="caption">What was it?</span>
      <input class="field" type="text" maxlength="80" placeholder="Masala dosa at the café" bind:value={oneOffName} />
    </label>

    <div class="stack">
      <span class="caption">Values for the whole thing</span>
      <div class="list">
        {#each nutrients as n (n.id)}
          <label class="list-row">
            <span class:protein={n.id === 'protein'}>{n.name}</span>
            <span class="value-input">
              <input class="field number" type="text" inputmode="decimal" placeholder="—" aria-label="{n.name} in {n.unit}" oninput={(e) => readValue(n.id, e)} />
              <span class="unit-label">{n.unit}</span>
            </span>
          </label>
        {/each}
      </div>
      <p class="note">Leave a value blank if you don't know it. Blank means unknown, not zero.</p>
    </div>

    <div class="time-row">
      <span class="caption">Time</span>
      <TimePicker bind:value={when} />
    </div>

    <button type="button" class="primary-button big pressable" disabled={!oneOffValid} onclick={logOneOff}>
      {oneOffValid ? 'Log it' : 'Add a name and a value'}
    </button>
  {/if}
</Sheet>

<style>
  .head {
    display: flex;
    align-items: flex-start;
    gap: 6px;
  }

  .title-block {
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1;
    min-width: 0;
    padding-top: 6px;
  }

  .sheet-title {
    font: 800 26px/1.1 var(--display);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .icon-button {
    display: flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: 44px;
    height: 44px;
    margin-left: -10px;
    border: 0;
    background: transparent;
    color: var(--ink);
  }

  .icon-button[aria-pressed] {
    margin-left: 0;
    margin-right: -10px;
  }

  .actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .search {
    width: 100%;
    height: 48px;
    padding: 0 14px;
    border-radius: 12px;
    background: var(--raised);
    border-color: var(--raised);
  }

  .food-row {
    width: 100%;
    border: 0;
    border-radius: 0;
    background: transparent;
    text-align: left;
    color: var(--ink-2);
  }

  .list .food-row + .food-row {
    border-top: 1px solid var(--line);
  }

  .food-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding: 6px 0;
  }

  .food-name {
    font-size: 15px;
    font-weight: 600;
    color: var(--ink);
  }

  .caption {
    font: 700 13px/1 var(--display);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .time-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    min-height: 44px;
  }

  .big {
    flex: none;
    height: 58px;
    border-radius: 14px;
    font-size: 20px;
  }

  .value-input {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .number {
    width: 96px;
    text-align: right;
  }

  .unit-label {
    width: 32px;
    font-size: 13px;
    color: var(--ink-3);
  }

  .protein {
    color: var(--protein);
  }
</style>
