import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'node:path'

// Multi-page build: the URLs stay exactly as before (/interview.html?id=..., /report.html?id=...),
// so links already sent to candidates keep working. FastAPI serves dist/.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        interview: resolve(__dirname, 'interview.html'),
        dashboard: resolve(__dirname, 'dashboard.html'),
        hr: resolve(__dirname, 'hr.html'),
        report: resolve(__dirname, 'report.html'),
      },
    },
  },
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/media': 'http://127.0.0.1:8000', '/llm': 'http://127.0.0.1:8000' } },
})
