import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '../styles.css'
import InterviewApp from '../interview/InterviewApp'

createRoot(document.getElementById('root')!).render(<StrictMode><InterviewApp /></StrictMode>)
