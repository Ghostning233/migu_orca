import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// MiGuOrca Stage 27 (US-197): the frontend is served same-origin by Flask at
// `/app/` (see apps/migu_orca_web/routes_app.py). `base` must stay an absolute
// path rooted at `/app/` so the built asset URLs work under Flask production
// hosting without a Node runtime. The dev server proxies `/api/v1` to the
// local Flask backend (see `server.proxy` below); everything else is served
// by Vite for local development only.
export default defineConfig({
  plugins: [vue()],
  base: '/app/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // US-199 will centralize API access; the dev proxy keeps Vite dev
      // (http://localhost:5173) able to call the Flask backend
      // (http://127.0.0.1:5000) during local development. Production never
      // uses this proxy — Flask serves the built SPA same-origin.
      '/api/v1': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // Deterministic, cacheable production output; Flask serves `dist/` from
    // `/app/static/` and the `/app/` fallback template (see routes_app.py).
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    // US-207: split the stable vendor runtime (vue/pinia/vue-router) into its
    // own hashed chunk so feature rebuilds don't invalidate the framework
    // cache, while keeping feature routes lazy. A functional manualChunks
    // keeps the vendor boundary explicit (an object form would group
    // everything into one chunk and defeat code-splitting).
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            return 'vendor'
          }
        },
      },
    },
  },
})
