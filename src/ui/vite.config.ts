import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// In Docker, VITE_API_URL points to the gateway service name.
// Locally, falls back to localhost:8000.
declare const process: { env: Record<string, string | undefined> };
const gatewayTarget = process.env.VITE_API_URL || 'http://localhost:8000';
const wsTarget = gatewayTarget.replace(/^http/, 'ws');

export default defineConfig({
  plugins: [
    tailwindcss(), // MUST be before react()
    react(),
  ],
  server: {
    proxy: {
      '/threads': {
        target: gatewayTarget,
        changeOrigin: true,
      },
      '/team': {
        target: gatewayTarget,
        changeOrigin: true,
      },
      '/teams': {
        target: gatewayTarget,
        changeOrigin: true,
      },
      '/permissions': {
        target: gatewayTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: wsTarget,
        ws: true,
      },
    },
  },
});
