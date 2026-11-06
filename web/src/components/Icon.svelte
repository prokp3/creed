<script>
  const PATHS = {
    swim:
      'M18.5 7a2 2 0 1 1-4 0a2 2 0 1 1 4 0 M5 12l4.5-3.5 3 2.5 3.5-1 M2.5 16c1.6 0 1.6-1.2 3.2-1.2s1.6 1.2 3.2 1.2 1.6-1.2 3.1-1.2 1.6 1.2 3.2 1.2 1.6-1.2 3.2-1.2 1.6 1.2 3.1 1.2 M2.5 20c1.6 0 1.6-1.2 3.2-1.2s1.6 1.2 3.2 1.2 1.6-1.2 3.1-1.2 1.6 1.2 3.2 1.2 1.6-1.2 3.2-1.2 1.6 1.2 3.1 1.2',
    bike:
      'M9 16.5a3.5 3.5 0 1 1-7 0a3.5 3.5 0 1 1 7 0 M22 16.5a3.5 3.5 0 1 1-7 0a3.5 3.5 0 1 1 7 0 M5.5 16.5L9 9h6.5l3 7.5 M9 9l3.5 7.5h-7 M15.5 9l-.8-2.5H17 M9 9L8.2 7H6.5',
    run: 'M17 4.5a2 2 0 1 1-4 0a2 2 0 1 1 4 0 M6 11l4-3.5 4 1.5 2.5 3H20 M10.5 9.5L12 14l-3 3.5L5 18 M12 14l3.5 2.5.5 4.5',
    other: 'M12 3v18 M3 12h18',
    multisport: 'M4 12h16 M12 4l8 8-8 8',
    settings: 'M4 7h10 M18 7h2 M4 17h2 M10 17h10 M18 7a2 2 0 1 1-4 0a2 2 0 1 1 4 0 M10 17a2 2 0 1 1-4 0a2 2 0 1 1 4 0',
    refresh: 'M20 12a8 8 0 1 1-2.34-5.66 M20 4v4h-4',
    back: 'M15 5l-7 7 7 7',
    forward: 'M9 5l7 7-7 7',
    down: 'M6 9l6 6 6-6',
    warning: 'M12 3.5L22 20.5H2z M12 10v5 M12 18h.01',
  };

  let { name, size = 24, stroke = 2, label = null } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width={stroke}
  stroke-linecap="round"
  stroke-linejoin="round"
  role={label ? 'img' : undefined}
  aria-label={label}
  aria-hidden={label ? undefined : 'true'}
>
  <path d={PATHS[name] || PATHS.other} />
</svg>
