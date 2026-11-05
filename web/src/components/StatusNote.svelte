<script>
  // What a screen shows while it has nothing to show, or when the server can't be reached.
  let { resource: res, what = 'this screen' } = $props();
</script>

{#if res.error}
  <div class="gutter">
    <div class="card note" role="alert">
      {#if res.error.status === 401}
        Sign-in isn't set up yet, so {what} can't load.
      {:else}
        {res.error.message}{res.data ? " You're seeing the last numbers that loaded." : ''}
      {/if}
    </div>
  </div>
{:else if !res.data}
  <div class="gutter"><p class="note" role="status">Loading…</p></div>
{/if}
