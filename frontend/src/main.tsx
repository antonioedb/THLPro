import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App'
import { AuthProvider } from './store/auth'
import { defaultPreferences } from './store/preferences'

const queryClient = new QueryClient()
const storedTheme = (JSON.parse(localStorage.getItem('thlpro_preferences') || '{}').theme || defaultPreferences.theme) as 'light' | 'dark'
if (storedTheme === 'dark') document.documentElement.classList.add('dark')
else document.documentElement.classList.remove('dark')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
