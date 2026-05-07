import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 从环境变量读取后端端口，默认 8000
const backendPort = process.env.BACKEND_PORT || 8000

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
})
