import express from 'express'
import { createProxyMiddleware } from 'http-proxy-middleware'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const app = express()
const PORT = process.env.PORT || 3000

// Proxy /ckan/* → CKAN API, stripping headers that trigger WAF rejections
app.use('/ckan', createProxyMiddleware({
  target: 'https://open.canada.ca',
  changeOrigin: true,
  pathRewrite: { '^/ckan': '/data/en/api/3/action' },
  on: {
    proxyReq(proxyReq) {
      proxyReq.removeHeader('origin')
      proxyReq.removeHeader('referer')
      proxyReq.setHeader(
        'User-Agent',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
      )
      proxyReq.setHeader('Accept', 'application/json, text/plain, */*')
      proxyReq.setHeader('Accept-Language', 'en-CA,en-US;q=0.9,en;q=0.8')
    },
  },
}))

// Serve Vite build (base: '/ev/') as static files
app.use('/ev', express.static(join(__dirname, 'dist')))

// SPA fallback — any /ev/* path returns index.html
app.get('/ev/*splat', (req, res) => {
  res.sendFile(join(__dirname, 'dist', 'index.html'))
})

// Redirect bare root to /ev
app.get('/', (req, res) => res.redirect('/ev'))

app.listen(PORT, () => console.log(`Listening on port ${PORT}`))
