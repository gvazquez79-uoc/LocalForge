import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { LogsPage } from './components/LogsPage.tsx'
import { initTheme } from './store/theme.ts'

initTheme();

const isLogsPage = window.location.pathname === '/logs';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isLogsPage ? <LogsPage /> : <App />}
  </StrictMode>,
)
