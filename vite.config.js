import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Must match your repo name so assets resolve on GitHub Pages.
  base: '/congress-tracker/',
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  server: {
    port: 5173,
    strictPort: false,
  },
})
