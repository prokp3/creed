<script>
  // A coloured circle around a discipline's icon. The text beside it takes the same colour via its class.
  import Icon from './Icon.svelte';

  let { discipline, size = 56, label = null } = $props();
  const known = $derived(['run', 'bike', 'swim'].includes(discipline));
  const border = $derived(size >= 50 ? 3 : 2);
  const icon = $derived(Math.round(size * (discipline === 'bike' ? 0.55 : 0.5)));
</script>

<span
  class="circle"
  class:swim={discipline === 'swim'}
  class:bike={discipline === 'bike'}
  class:run={discipline === 'run'}
  style:width="{size}px"
  style:height="{size}px"
  style:border-width="{border}px"
  style:border-color={known ? 'var(--discipline)' : 'var(--ink-3)'}
  style:color={known ? 'var(--discipline)' : 'var(--ink-2)'}
>
  <Icon name={discipline} size={icon} stroke={size >= 40 ? 2 : 2.4} {label} />
</span>

<style>
  .circle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border-style: solid;
    border-radius: 50%;
  }
</style>
