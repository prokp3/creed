<script>
  let { why, confidence = null, title = 'Why this number' } = $props();
</script>

{#if why}
  <details class="why">
    <summary class="pressable">{title}</summary>
    <div class="body">
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
  </details>
{/if}

<style>
  summary {
    display: flex;
    align-items: center;
    min-height: 44px;
    list-style: none;
    color: var(--ink-2);
    font: 700 14px/1 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
    cursor: pointer;
  }

  summary::-webkit-details-marker {
    display: none;
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
