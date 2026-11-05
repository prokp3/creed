<script>
  // A run or ride drawn from the watch's GPS. The map library is large, so it's only downloaded when this screen
  // opens. OpenFreeMap supplies the map itself and needs no key. Its requests show which area is being viewed, so
  // nothing is asked for until someone chooses to open a map.
  import { onDestroy, onMount } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import Screen from '../components/Screen.svelte';
  import { get } from '../lib/api.js';

  const MAP_STYLE = 'https://tiles.openfreemap.org/styles/dark';
  const EDGE_PADDING = 56;
  const MAX_ZOOM = 18;
  const DARK = '#08080a';

  let { id } = $props();

  let holder = $state();
  let status = $state('loading');
  let problem = $state('');
  let route = $state(null);
  let map;
  let gone = false;

  const cssColor = (name) => getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();

  function draw(trail) {
    const colour = cssColor(trail.discipline);
    map.addSource('route', {
      type: 'geojson',
      data: { type: 'Feature', properties: {}, geometry: { type: 'MultiLineString', coordinates: trail.segments } },
    });
    map.addSource('ends', {
      type: 'geojson',
      data: {
        type: 'FeatureCollection',
        features: [
          // Finish first, so a loop's smaller start dot sits on top and both stay visible.
          { type: 'Feature', properties: { end: 'finish' }, geometry: { type: 'Point', coordinates: trail.finish } },
          { type: 'Feature', properties: { end: 'start' }, geometry: { type: 'Point', coordinates: trail.start } },
        ],
      },
    });
    const rounded = { 'line-cap': 'round', 'line-join': 'round' };
    map.addLayer({ id: 'route-edge', type: 'line', source: 'route', layout: rounded, paint: { 'line-color': DARK, 'line-width': 7 } });
    map.addLayer({ id: 'route-line', type: 'line', source: 'route', layout: rounded, paint: { 'line-color': colour, 'line-width': 4 } });
    map.addLayer({
      id: 'route-ends',
      type: 'circle',
      source: 'ends',
      paint: {
        'circle-radius': ['match', ['get', 'end'], 'start', 5, 9],
        'circle-color': ['match', ['get', 'end'], 'start', '#ffffff', colour],
        'circle-stroke-color': DARK,
        'circle-stroke-width': 2,
      },
    });
  }

  async function openMap(trail) {
    const [maplibre, worker] = await Promise.all([
      import('maplibre-gl'),
      import('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'),
      import('maplibre-gl/dist/maplibre-gl.css'),
    ]);
    if (gone) return;
    maplibre.setWorkerUrl(worker.default);
    map = new maplibre.Map({
      container: holder,
      style: MAP_STYLE,
      bounds: trail.bounds,
      fitBoundsOptions: { padding: EDGE_PADDING, maxZoom: 16 },
      maxZoom: MAX_ZOOM,
      dragRotate: false,
      touchPitch: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.on('load', () => {
      draw(trail);
      status = 'ready';
    });
    map.on('error', (event) => {
      // A single missing map square is normal. Only losing the whole map is worth telling someone about.
      if (status === 'loading') {
        status = 'failed';
        problem = event.error?.message || '';
      }
    });
  }

  onMount(async () => {
    try {
      route = await get(`/api/activities/${id}/route`);
      if (route.segments.length) await openMap(route);
      else status = 'empty';
    } catch (failure) {
      status = 'failed';
      problem = failure.message;
    }
  });

  onDestroy(() => {
    gone = true;
    map?.remove();
  });
</script>

<Screen fill>
  <div class="gutter top">
    <a class="back pressable" href="#/activities/{id}" aria-label="Back to this activity"><Icon name="back" size={22} stroke={2.4} /></a>
    <h1 class="page-heading">Route</h1>
  </div>

  <div class="area">
    <div class="map" bind:this={holder}></div>

    {#if status === 'loading'}
      <p class="center note" role="status">Loading the map…</p>
    {:else if status === 'empty'}
      <p class="center" role="status">{route.reason}</p>
    {:else if status === 'failed'}
      <div class="center stack" role="alert">
        <p>The map couldn't load. Check your connection and try again.</p>
        {#if problem}<p class="note">{problem}</p>{/if}
      </div>
    {:else}
      <div class="legend note {route.discipline}">
        <span><i class="dot start"></i>Start</span>
        <span><i class="dot finish"></i>Finish</span>
        {#if route.gaps}<span>Gaps: the watch paused or lost GPS</span>{/if}
        {#if route.incomplete}<span>Only part of this recording could be read</span>{/if}
      </div>
    {/if}
  </div>
</Screen>

<style>
  .top {
    flex: none;
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 44px;
  }

  .back {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    margin-left: -12px;
  }

  .area {
    position: relative;
    flex: 1;
    min-height: 0;
    background: var(--card);
  }

  .map {
    position: absolute;
    inset: 0;
  }

  .center {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0 var(--gutter);
    text-align: center;
  }

  .legend {
    position: absolute;
    top: 8px;
    left: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 2px 12px;
    max-width: calc(100% - 16px);
    padding: 6px 10px;
    border-radius: 8px;
    background: var(--bg);
    color: var(--ink-2);
  }

  .legend span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }

  .start {
    background: #fff;
  }

  .finish {
    background: var(--discipline);
  }

  /* The credit the map's makers require stays in full view, in the app's colours rather than a white pill. */
  .area :global(.maplibregl-ctrl-attrib),
  .area :global(.maplibregl-ctrl-attrib.maplibregl-compact) {
    background: var(--bg);
    color: var(--ink-2);
  }

  .area :global(.maplibregl-ctrl-attrib a) {
    color: var(--ink-2);
  }

  .area :global(.maplibregl-ctrl-attrib-button) {
    filter: invert(1);
  }
</style>
