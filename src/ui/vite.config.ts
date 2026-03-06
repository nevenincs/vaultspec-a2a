import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// In Docker, VITE_API_URL points to the API service name.
// Locally, falls back to localhost:8000.
declare const process: { env: Record<string, string | undefined> };
const apiTarget = process.env.VITE_API_URL || 'http://localhost:8000';
const wsTarget = apiTarget.replace(/^http/, 'ws');

export default defineConfig({
  plugins: [
    tailwindcss(), // MUST be before react()
    react(),
  ],
  server: {
    proxy: {
      '/threads': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/team': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/teams': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/permissions': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: wsTarget,
        ws: true,
      },
    },
  },
});
