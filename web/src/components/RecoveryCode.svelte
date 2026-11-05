<script>
  // Shown once, ever, so there's no moving on until the person says it's saved.
  let { code, onsaved } = $props();

  let saved = $state(false);
  let copied = $state(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      // Some browsers refuse. The code can still be selected and copied by hand.
    }
  }
</script>

<div class="stack holder">
  <p class="code">{code}</p>
  <button class="secondary-button pressable" onclick={copy}>{copied ? 'Copied' : 'Copy'}</button>
  <label class="confirm">
    <input type="checkbox" bind:checked={saved} />
    <span>I've saved it somewhere safe</span>
  </label>
  <button class="primary-button pressable" disabled={!saved} onclick={onsaved}>Continue</button>
</div>

<style>
  .holder {
    gap: 12px;
  }

  .code {
    padding: 14px 12px;
    border-radius: 8px;
    background: var(--card);
    font: 700 22px/1.3 var(--display);
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.04em;
    text-align: center;
    overflow-wrap: anywhere;
    -webkit-user-select: all;
    user-select: all;
  }

  .confirm {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 44px;
  }

  .confirm input {
    flex: none;
    width: 22px;
    height: 22px;
    margin: 0;
    accent-color: var(--ink);
  }
</style>
