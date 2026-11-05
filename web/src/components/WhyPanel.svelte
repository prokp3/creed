<script>
  import { slide } from 'svelte/transition';
  import { revealMs } from '../lib/motion.js';

  let { why, confidence = null, title = 'Why this number' } = $props();
  let open = $state(false);
</script>

{#if why}
  <div class="why">
    <button class="toggle pressable" aria-expanded={open} onclick={() => (open = !open)}>{title}</button>
    {#if open}
      <div class="body" transition:slide={{ duration: revealMs() }}>
        <p><b>Formula.</b> {why.formula}</p>
        <p><b>Inputs.</b> {why.inputs}</p>
        <p><b>Window.</b> {why.window}</p>
        {#if confidence}
          <p><b>Confidence.</b> {confidence[0].toUpperCase() + confidence.slice(1)}.</p>
        {/if}
        <p><b>Source.</b> {why.citation}</p>
        {#if why.note}
          <p class="quiet">{why.note}</p>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .toggle {
    display: flex;
    align-items: center;
    width: 100%;
    min-height: 44px;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--ink-2);
    font: 700 14px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
    text-align: left;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px;
    border-radius: 8px;
    background: var(--card);
    font-size: 12px;
    color: var(--ink-2);
    -webkit-user-select: text;
    user-select: text;
  }

  b {
    color: var(--ink);
    font-weight: 600;
  }

  .quiet {
    color: var(--ink-3);
  }
</style>
