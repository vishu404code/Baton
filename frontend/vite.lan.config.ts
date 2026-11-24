// LAN / demo mode: the browser talks only to this dev server, which proxies the API and the
// WebSocket to the backend. One URL for every laptop; no CORS or blocked-port surprises.
//   npx vite --config vite.lan.config.ts --mode lan
import { defineConfig, mergeConfig } from 'vite';
import base from './vite.config';

const BACKEND = process.env.BATON_BACKEND || 'http://localhost:8000';

export default mergeConfig(
  base,
  defineConfig({
    server: {
      port: 5175,
      host: true,
      strictPort: true,
      proxy: {
        '/api': { target: BACKEND, changeOrigin: true },
        '/health': { target: BACKEND, changeOrigin: true },
        '/mcp': { target: BACKEND, changeOrigin: true },
        '/ws': { target: BACKEND.replace(/^http/, 'ws'), ws: true, changeOrigin: true },
      },
    },
  }),
);
