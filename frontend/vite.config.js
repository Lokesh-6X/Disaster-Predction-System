import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The dev server forwards API and WebSocket calls to the backend, so the
// browser only ever talks to http://localhost:5173.
const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Keep the large charting library in its own cacheable file
        manualChunks: { charts: ['recharts'], react: ['react', 'react-dom', 'react-router-dom'] },
      },
    },
  },
  test: {
    environment: 'node',
  },
});
