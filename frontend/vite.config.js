import { defineConfig } from 'vite';
export default defineConfig({
  server: {proxy: {'/api': {target: 'http://127.0.0.1:8000', rewrite: path => path.replace(/^\/api/, '')}}},
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react-vendor';
          if (id.includes('node_modules/lucide-react/')) return 'icons';
        },
      },
    },
  },
});
