<script>
  // What a screen shows while it has nothing to show, or when the server can't be reached.
  let { resource: res } = $props();
</script>

{#if res.error}
  <div class="gutter">
    <div class="card note" role="alert">
      {res.error.message}{res.data ? " You're seeing the last numbers that loaded." : ''}
    </div>
  </div>
{:else if !res.data}
  <div class="gutter"><p class="note" role="status">Loading…</p></div>
{/if}
