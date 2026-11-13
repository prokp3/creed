import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

// Local development only: the dev server sends the session from .dev-token unless the browser has its own, so
// you start signed in and it never reaches browser code or the built app. tools/dev_api.py creates the file and
// the session. Start that first.
const tokenFile = new URL('../.dev-token', import.meta.url);
const devToken = existsSync(tokenFile) ? readFileSync(tokenFile, 'utf8').trim() : '';

export default defineConfig({
  plugins: [svelte()],
  server: {
    // Passkeys need a domain name, and localhost counts where 127.0.0.1 doesn't.
    host: 'localhost',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (outgoing, incoming) => {
            if (devToken && !/(^|;\s*)creed_session=/.test(incoming.headers.cookie ?? '')) {
              outgoing.setHeader('Cookie', `creed_session=${devToken}`);
            }
          });
        },
      },
    },
  },
  // The app at /, and the public pages: the homepage (/welcome/), Try Creed (/try/) and feedback (/feedback/).
  build: {
    rollupOptions: {
      input: {
        app: fileURLToPath(new URL('./index.html', import.meta.url)),
        welcome: fileURLToPath(new URL('./welcome/index.html', import.meta.url)),
        try: fileURLToPath(new URL('./try/index.html', import.meta.url)),
        feedback: fileURLToPath(new URL('./feedback/index.html', import.meta.url)),
      },
    },
  },
  test: { include: ['src/**/*.test.js'] },
});
