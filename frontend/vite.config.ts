/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The dev proxy keeps the browser same-origin with the API, so no CORS setup is needed.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The dev-only export page reads the provider and model names from backend/config/agents*.yaml.
    fs: { allow: ['..'] },
    proxy: {
      '/api': { target: process.env.API_TARGET ?? 'http://127.0.0.1:8765', changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
    css: false,
    testTimeout: 20000,
  },
})
