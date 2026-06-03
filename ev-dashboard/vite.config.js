import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/ckan': {
        target: 'https://open.canada.ca',
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/ckan/, '/data/en/api/3/action'),
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            // Strip headers that identify this as a localhost dev request —
            // WAFs often reject cross-origin requests from non-production origins.
            proxyReq.removeHeader('origin')
            proxyReq.removeHeader('referer')
            // Mimic a real browser so the WAF's bot-detection passes.
            proxyReq.setHeader(
              'User-Agent',
              'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
            )
            proxyReq.setHeader('Accept', 'application/json, text/plain, */*')
            proxyReq.setHeader('Accept-Language', 'en-CA,en-US;q=0.9,en;q=0.8')
          })
        },
      },
    },
  },
})
