import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '../styles.css'
import Dashboard from '../hr/Dashboard'

createRoot(document.getElementById('root')!).render(<StrictMode><Dashboard /></StrictMode>)
