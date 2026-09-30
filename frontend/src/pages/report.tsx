import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '../styles.css'
import Report from '../hr/Report'

createRoot(document.getElementById('root')!).render(<StrictMode><Report /></StrictMode>)
