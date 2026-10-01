// Vercel Routing Middleware: forwards /api and /media to the backend named by the BACKEND_URL environment
// variable (Vercel > Project > Settings > Environment Variables). The browser keeps talking to the Vercel
// address only, so sign-in cookies work without CORS. Not used on Render or in local development.
import { rewrite } from '@vercel/functions/middleware'

export const config = { matcher: ['/api/:path*', '/media/:path*'] }

export default function middleware(request: Request): Response {
  const backend = (process.env.BACKEND_URL || '').trim().replace(/\/+$/, '')
  if (!/^https?:\/\//.test(backend)) {
    return new Response(JSON.stringify({ detail: 'BACKEND_URL is not set on Vercel. Add it under Project > Settings > Environment Variables, then redeploy.' }),
      { status: 503, headers: { 'content-type': 'application/json' } })
  }
  const url = new URL(request.url)
  return rewrite(new URL(url.pathname + url.search, backend))
}
