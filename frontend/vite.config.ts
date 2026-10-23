import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'node:path'
import { execSync } from 'node:child_process'

// The commit this build came from, shown on the interview page so anyone can check the live site runs the latest code.
const build = (process.env.VERCEL_GIT_COMMIT_SHA || process.env.RENDER_GIT_COMMIT || (() => {
  try { return execSync('git rev-parse HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString() } catch { return 'dev' }
})()).trim().slice(0, 7)

// Two pages: the web app (index.html: landing, sign-in, workspace, careers; FastAPI serves it for every app route)
// and the candidate's interview call (interview.html?id=..., so links already sent keep working).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __BUILD__: JSON.stringify(build) },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'index.html'),
        interview: resolve(__dirname, 'interview.html'),
      },
    },
  },
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/media': 'http://127.0.0.1:8000', '/llm': 'http://127.0.0.1:8000' } },
})
