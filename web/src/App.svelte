<script>
  // A plain single-page app. Each tab stays mounted once visited, so it keeps its place and opens instantly.
  // None of it exists until you're signed in, and signing out removes it, numbers included.
  import { onMount } from 'svelte';
  import { auth, checkAuth } from './lib/auth.svelte.js';
  import { changeScreen, motionBetween } from './lib/motion.js';
  import { refreshRace } from './lib/race.svelte.js';
  import Today from './screens/Today.svelte';
  import InDepth from './screens/InDepth.svelte';
  import Activities from './screens/Activities.svelte';
  import ActivityDetail from './screens/ActivityDetail.svelte';
  import ActivityMap from './screens/ActivityMap.svelte';
  import Settings from './screens/Settings.svelte';
  import SignIn from './screens/SignIn.svelte';

  const TABS = [
    { id: 'today', label: 'Today' },
    { id: 'in-depth', label: 'In-Depth' },
    { id: 'activities', label: 'Activities' },
  ];

  function parse(hash) {
    const [name, id, part] = hash.replace(/^#\/?/, '').split('/');
    if (name === 'settings') return { screen: 'settings', tab: null };
    if (name === 'activities' && id && part === 'map') return { screen: 'activity-map', tab: 'activities', id };
    if (name === 'activities' && id) return { screen: 'activity', tab: 'activities', id };
    if (TABS.some((t) => t.id === name)) return { screen: name, tab: name };
    return { screen: 'today', tab: 'today' };
  }

  let route = $state(parse(location.hash));
  let visited = $state(new Set([parse(location.hash).screen]));
  let freshness = $state(0);

  function onhashchange() {
    const next = parse(location.hash);
    changeScreen(motionBetween(route.screen, next.screen), () => {
      route = next;
      visited = new Set([...visited, next.screen]);
    });
  }

  // Coming back to the app after a while should show current numbers.
  function onvisibilitychange() {
    if (document.visibilityState !== 'visible') return;
    if (auth.status === 'signed-in') {
      freshness += 1;
      refreshRace();
    } else if (auth.status === 'unreachable') {
      checkAuth();
    }
  }

  onMount(checkAuth);

  $effect(() => {
    if (auth.status === 'signed-in') refreshRace();
  });
</script>

<svelte:window {onhashchange} />
<svelte:document {onvisibilitychange} />

{#if auth.status === 'signed-in'}
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
  {#if route.screen === 'activity-map'}
    <ActivityMap id={route.id} />
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
{:else if auth.status === 'signed-out'}
  <SignIn hasPasskey={auth.hasPasskey} onfinished={checkAuth} />
{:else if auth.status === 'unreachable'}
  <div class="unreachable gutter stack">
    <p role="alert">{auth.problem}</p>
    <button class="primary-button pressable" onclick={checkAuth}>Try again</button>
  </div>
{/if}

<style>
  .unreachable {
    flex: 1;
    justify-content: center;
    gap: 12px;
  }

  nav {
    flex: none;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    padding-bottom: var(--safe-bottom);
    border-top: 1px solid var(--line);
    background: var(--bg);
    view-transition-name: tabbar;
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
    transition: color 0.18s ease, border-color 0.18s ease, opacity 0.12s ease, transform 0.18s var(--ease);
  }

  a.current {
    border-top-color: var(--ink);
    color: var(--ink);
  }
</style>
