import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Poppins is served from our own domain (Latin subset, ~8 KB per weight,
// downloaded only when a weight is used) instead of Google Fonts, which cost
// a slow extra connection before the first page could show its text.
import '@fontsource/poppins/latin-400.css'
import '@fontsource/poppins/latin-500.css'
import '@fontsource/poppins/latin-600.css'
import '@fontsource/poppins/latin-700.css'
import '@fontsource/poppins/latin-800.css'
import './styles/tokens.css'
import './styles/app.css'
import './styles/analytics.css'
import App from './App.jsx'
import { AuthProvider } from './auth/AuthContext.jsx'
import { i18nReady } from './i18n/index.js'

// Opens the app with no connection (public/sw.js). Production only: in
// development it would serve stale modules over Vite's hot reload.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}))
}

i18nReady.then(() => createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>,
))
