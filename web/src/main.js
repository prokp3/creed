import '@fontsource/barlow/400.css';
import '@fontsource/barlow/500.css';
import '@fontsource/barlow/600.css';
import '@fontsource/barlow-condensed/600.css';
import '@fontsource/barlow-condensed/700.css';
import '@fontsource/barlow-condensed/800.css';
import './app.css';
import { mount } from 'svelte';
import App from './App.svelte';
import { installHaptics } from './lib/haptics.js';

installHaptics();
// iOS only shows the pressed look on buttons once a page listens for touches.
document.addEventListener('touchstart', () => {}, { passive: true });

mount(App, { target: document.getElementById('app') });

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js');
}
