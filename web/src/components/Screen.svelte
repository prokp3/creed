<script>
  // One tab's scrolling page. The bib sits at the top and scrolls away, then a slim version takes over,
  // so the countdown stays on screen without using a fifth of it. With `fill`, as on the map, the page doesn't
  // scroll: the slim countdown stays put and the content takes the rest of the screen.
  import Bib from './Bib.svelte';
  import { race } from '../lib/race.svelte.js';

  const COMPACT_AFTER = 130;

  let { active = true, fill = false, children } = $props();
  let compact = $state(false);

  function onscroll(event) {
    compact = event.currentTarget.scrollTop > COMPACT_AFTER;
  }
</script>

<div class="screen" hidden={!active}>
  <div class="frame">
    <div class="compact" class:show={compact} class:fixed={fill} aria-hidden="true">
      <span class="race">70.3 GOA</span>
      <span class="time">
        <b>{race.parts.days}</b>D <b>{race.parts.hours}</b>H <b>{race.parts.minutes}</b>M <b>{race.parts.seconds}</b>S
      </span>
    </div>
    {#if fill}
      <div class="filled">{@render children()}</div>
    {:else}
      <div class="scroll" {onscroll}>
        <div class="content">
          <Bib />
          {@render children()}
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .screen {
    flex: 1;
    min-height: 0;
    display: flex;
    padding-top: var(--safe-top);
    background: var(--bg);
  }

  .screen[hidden] {
    display: none;
  }

  .frame {
    position: relative;
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }

  .scroll::-webkit-scrollbar {
    display: none;
  }

  .content {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-bottom: 20px;
  }

  .filled {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .compact {
    position: absolute;
    z-index: 2;
    top: 0;
    left: 0;
    right: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px var(--gutter) 8px;
    /* The same colour as the status bar above it, so the two read as one bar. */
    background: var(--bg);
    border-bottom: 1px solid var(--line);
    color: var(--ink);
    transform: translateY(-100%);
    transition: transform 0.22s var(--ease);
  }

  .compact.show {
    transform: none;
  }

  .compact.fixed {
    position: static;
    flex: none;
    transform: none;
    transition: none;
  }

  /* The same small brand band as the bib, not a wall of red, because red otherwise means attention. */
  .race {
    padding: 3px 6px;
    border-radius: 3px;
    background: var(--brand);
    color: #fff;
    font: 800 15px/1 var(--display);
    letter-spacing: 0.05em;
  }

  .time {
    font: 600 14px/1 var(--display);
    letter-spacing: 0.03em;
    font-variant-numeric: tabular-nums;
  }

  .time b {
    font-weight: 800;
    font-size: 17px;
  }
</style>
