import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        runtimeCaching: [
          {
            // Network-first for API calls
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkFirst',
            options: { cacheName: 'api-cache', networkTimeoutSeconds: 10 },
          },
          {
            // Cache-first for static assets
            urlPattern: ({ request }) =>
              request.destination === 'script' ||
              request.destination === 'style' ||
              request.destination === 'font',
            handler: 'CacheFirst',
            options: { cacheName: 'static-cache', expiration: { maxAgeSeconds: 86400 * 30 } },
          },
        ],
      },
      manifest: {
        name: 'Olympus — ASMO Personas',
        short_name: 'Olympus',
        description: 'Personal AI assistants: Alita, FEMTO, GIORGIO',
        theme_color: '#1a1410',
        background_color: '#1a1410',
        display: 'standalone',
        orientation: 'portrait',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
      includeAssets: ['favicon.ico', 'icons/*.png', 'assets/personas/*.png'],
    }),
  ],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
    },
  },
  resolve: {
    alias: { '@': '/src' },
  },
})
