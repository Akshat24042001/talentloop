import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import App from './App'
import { installLinkInterceptor } from './lib/router'
import { installPrefetch, prefetchRoute } from './lib/prefetch'
import { prefetch } from './lib/api'
import './lib/theme'

installLinkInterceptor()
installPrefetch()
if (location.pathname.startsWith('/app')) { prefetch('/api/auth/me'); prefetchRoute(location.pathname + location.search) }   // in parallel, not after sign-in
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
