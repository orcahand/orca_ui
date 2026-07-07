import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build lands inside the Python package so the wheel can ship it.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../orca_ui/webui',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:5001',
      '/assets/hand': 'http://localhost:5001',
      '/ws': { target: 'ws://localhost:5001', ws: true },
    },
  },
})
