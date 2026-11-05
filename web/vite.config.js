import { existsSync, readFileSync } from 'node:fs';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

// Local development only: the dev server adds the token to API calls, so it never reaches browser code
// or the built app. tools/dev_api.py creates the file. Start that first.
const tokenFile = new URL('../.dev-token', import.meta.url);
const devToken = existsSync(tokenFile) ? readFileSync(tokenFile, 'utf8').trim() : '';

export default defineConfig({
  plugins: [svelte()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        headers: devToken ? { Authorization: `Bearer ${devToken}` } : {},
      },
    },
  },
  test: { include: ['src/**/*.test.js'] },
});
