import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import App from './App'
import { installLinkInterceptor } from './lib/router'
import './lib/theme'

installLinkInterceptor()
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
