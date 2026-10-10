import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { viteStaticCopy } from 'vite-plugin-static-copy'

const backendUrl = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

// Detección de voz (VAD) en el navegador: el modelo Silero, el worklet de audio y el
// runtime wasm de onnxruntime se sirven desde /vad/ en vez de un CDN, para que el modo
// voz funcione sin depender de internet (igual que Whisper y Piper en el backend).
const vadAssets = viteStaticCopy({
  targets: [
    { src: 'node_modules/@ricky0123/vad-web/dist/vad.worklet.bundle.min.js', dest: 'vad' },
    { src: 'node_modules/@ricky0123/vad-web/dist/silero_vad_v5.onnx', dest: 'vad' },
    { src: 'node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded*.{wasm,mjs}', dest: 'vad' },
  ],
})

export default defineConfig({
  plugins: [tailwindcss(), react(), vadAssets],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/auth': backendUrl,
      '/chat': backendUrl,
      '/voice': backendUrl,
      '/dashboard': backendUrl,
    },
  },
})
