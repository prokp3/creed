<script>
  // A panel that slides up from the bottom, the way iPhone apps ask for one thing without leaving the screen.
  // Tap outside it, press Escape, or drag it down by its top edge to close it.
  import { cubicOut } from 'svelte/easing';
  import { fade, fly } from 'svelte/transition';
  import { revealMs } from '../lib/motion.js';

  const CLOSE_AFTER_PX = 90;

  let { label, onclose, tall = false, children } = $props();

  let dragStart = null;
  let dragged = $state(0);

  function onkeydown(event) {
    if (event.key === 'Escape') onclose();
  }

  function ontouchstart(event) {
    dragStart = event.touches[0].clientY;
  }

  function ontouchmove(event) {
    if (dragStart === null) return;
    dragged = Math.max(0, event.touches[0].clientY - dragStart);
  }

  function ontouchend() {
    const far = dragged > CLOSE_AFTER_PX;
    dragStart = null;
    dragged = 0;
    if (far) onclose();
  }

  const ms = revealMs() * 1.4;
</script>

<svelte:window {onkeydown} />

<div class="backdrop" role="presentation" onclick={onclose} transition:fade={{ duration: ms }}></div>
<div
  class="sheet"
  class:tall
  class:dragging={dragged > 0}
  role="dialog"
  aria-modal="true"
  aria-label={label}
  style:transform={dragged ? `translateY(${dragged}px)` : null}
  transition:fly={{ y: '100%', duration: ms, easing: cubicOut, opacity: 1 }}
>
  <div class="grip" role="presentation" {ontouchstart} {ontouchmove} {ontouchend} ontouchcancel={ontouchend}>
    <span class="handle" aria-hidden="true"></span>
  </div>
  <div class="body">
    {@render children()}
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    z-index: 20;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
  }

  .sheet {
    position: fixed;
    z-index: 21;
    left: 0;
    right: 0;
    bottom: 0;
    max-width: 600px;
    max-height: calc(100% - var(--safe-top) - 40px);
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    border-radius: 22px 22px 0 0;
    background: var(--sheet);
    transition: transform 0.25s var(--ease);
  }

  .sheet.tall {
    height: calc(100% - var(--safe-top) - 40px);
  }

  .sheet.dragging {
    transition: none;
  }

  .grip {
    flex: none;
    display: flex;
    justify-content: center;
    padding: 10px 0 8px;
    touch-action: none;
  }

  .handle {
    width: 40px;
    height: 5px;
    border-radius: 3px;
    background: var(--border);
  }

  .body {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 0 var(--gutter) calc(var(--safe-bottom) + 20px);
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-width: none;
  }

  .body::-webkit-scrollbar {
    display: none;
  }

  /* A long sheet scrolls rather than squashing its buttons. */
  .body > :global(*) {
    flex-shrink: 0;
  }
</style>
