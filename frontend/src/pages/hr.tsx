import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '../styles.css'
import NewInterview from '../hr/NewInterview'

createRoot(document.getElementById('root')!).render(<StrictMode><NewInterview /></StrictMode>)
