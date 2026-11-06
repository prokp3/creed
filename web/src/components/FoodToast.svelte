<script>
  // What just happened, with an undo for a few seconds. On the Food tab it sits beside the add button.
  import { fly } from 'svelte/transition';
  import { revealMs } from '../lib/motion.js';
  import { dismissToast, food, undoToast } from '../lib/food.svelte.js';

  let { besideButton = false } = $props();
</script>

{#if food.toast}
  {#key food.toast.id}
    <div class="toast" class:beside={besideButton} class:problem={food.toast.problem} role={food.toast.problem ? 'alert' : 'status'} transition:fly={{ y: 24, duration: revealMs() }}>
      <span class="text">{food.toast.text}</span>
      {#if food.toast.undo}
        <button type="button" class="action pressable" onclick={undoToast}>Undo</button>
      {:else}
        <button type="button" class="action pressable" aria-label="Dismiss" onclick={dismissToast}>OK</button>
      {/if}
    </div>
  {/key}
{/if}

<style>
  .toast {
    position: fixed;
    z-index: 15;
    left: var(--gutter);
    right: var(--gutter);
    bottom: calc(var(--safe-bottom) + 49px + 16px);
    max-width: 568px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 56px;
    padding: 6px 6px 6px 16px;
    border-radius: 14px;
    background: var(--raised);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  }

  /* The add button is 60px wide with a 16px gutter. */
  .toast.beside {
    right: calc(var(--gutter) + 76px);
  }

  .toast.problem {
    border: 1px solid var(--attention);
  }

  .text {
    flex: 1;
    min-width: 0;
    font-size: 14px;
  }

  .action {
    flex: none;
    height: 44px;
    padding: 0 12px;
    border: 0;
    background: transparent;
    color: var(--ink);
    font: 800 16px/1 var(--display);
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
</style>
