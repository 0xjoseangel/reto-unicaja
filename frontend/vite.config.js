import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backendUrl = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/auth': backendUrl,
      '/chat': backendUrl,
      '/transactions': backendUrl,
      '/voice': backendUrl,
      '/dashboard': backendUrl,
    },
  },
})
