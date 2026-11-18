/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Builds use relative asset paths, so the same files work at "/" (Docker) and under a sub-path such
// as GitHub Pages' /<repo>/seller-health/. Routes live in the URL hash, so the server never sees them.
// In development, /api is proxied to the FastAPI service, so the browser sees one origin.
export default defineConfig(({ command }) => ({
  base: command === 'build' ? './' : '/',
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
}))
