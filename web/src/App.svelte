<script>
  // A plain single-page app. Each tab stays mounted once visited, so it keeps its place and opens instantly.
  import { onMount } from 'svelte';
  import { refreshRace } from './lib/race.svelte.js';
  import Today from './screens/Today.svelte';
  import InDepth from './screens/InDepth.svelte';
  import Activities from './screens/Activities.svelte';
  import ActivityDetail from './screens/ActivityDetail.svelte';
  import Settings from './screens/Settings.svelte';

  const TABS = [
    { id: 'today', label: 'Today' },
    { id: 'in-depth', label: 'In-Depth' },
    { id: 'activities', label: 'Activities' },
  ];

  function parse(hash) {
    const [name, id] = hash.replace(/^#\/?/, '').split('/');
    if (name === 'settings') return { screen: 'settings', tab: null };
    if (name === 'activities' && id) return { screen: 'activity', tab: 'activities', id };
    if (TABS.some((t) => t.id === name)) return { screen: name, tab: name };
    return { screen: 'today', tab: 'today' };
  }

  let route = $state(parse(location.hash));
  let visited = $state(new Set([parse(location.hash).screen]));
  let freshness = $state(0);

  function onhashchange() {
    route = parse(location.hash);
    visited = new Set([...visited, route.screen]);
  }

  // Coming back to the app after a while should show current numbers.
  function onvisibilitychange() {
    if (document.visibilityState === 'visible') {
      freshness += 1;
      refreshRace();
    }
  }

  onMount(refreshRace);
</script>

<svelte:window {onhashchange} />
<svelte:document {onvisibilitychange} />

{#if visited.has('today')}
  <Today active={route.screen === 'today'} {freshness} />
{/if}
{#if visited.has('in-depth')}
  <InDepth active={route.screen === 'in-depth'} {freshness} />
{/if}
{#if visited.has('activities')}
  <Activities active={route.screen === 'activities'} {freshness} />
{/if}
{#if route.screen === 'activity'}
  <ActivityDetail id={route.id} />
{/if}
{#if visited.has('settings')}
  <Settings active={route.screen === 'settings'} onsaved={refreshRace} {freshness} />
{/if}

<nav aria-label="Main">
  {#each TABS as tab (tab.id)}
    <a href="#/{tab.id}" class="pressable" class:current={route.tab === tab.id} aria-current={route.tab === tab.id ? 'page' : undefined}>
      {tab.label}
    </a>
  {/each}
</nav>

<style>
  nav {
    flex: none;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    padding-bottom: var(--safe-bottom);
    border-top: 1px solid var(--line);
    background: var(--bg);
  }

  a {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 49px;
    margin-top: -1px;
    border-top: 2px solid transparent;
    color: var(--ink-3);
    font: 700 16px/1 var(--display);
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  a.current {
    border-top-color: var(--ink);
    color: var(--ink);
  }
</style>
