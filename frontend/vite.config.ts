import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build lands inside the Python package so the wheel can ship it.
// Two entries: the console (index.html) and the compact motor-bench page
// (bench.html, served by the backend at /bench).
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../orca_ui/webui',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        bench: resolve(__dirname, 'bench.html'),
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:5001',
      '/assets/hand': 'http://localhost:5001',
      '/ws': { target: 'ws://localhost:5001', ws: true },
    },
  },
})
