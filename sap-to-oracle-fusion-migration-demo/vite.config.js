import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Standard Vite + React config. No backend/proxy needed since this demo is fully client-side.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
  },
})
