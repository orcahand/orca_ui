import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Standalone web build of the assembly guide (no backend, no hand). Relative
// base so the guide can be served from any path.
export default defineConfig({
  plugins: [react()],
  base: './',
  define: { 'import.meta.env.VITE_ASSEMBLY_WEB': JSON.stringify('1') },
  build: {
    outDir: 'dist-assembly',
    emptyOutDir: true,
    rollupOptions: { input: 'assembly.html' },
  },
})
