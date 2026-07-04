import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/chat': 'http://localhost:8000',
      '/transactions': 'http://localhost:8000',
    },
  },
})
