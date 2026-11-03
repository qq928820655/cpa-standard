import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'

const pluginRoot = resolve(__dirname, '../plugins/video-world/frontend')

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: resolve(pluginRoot, 'dist'),
    emptyOutDir: true,
    lib: {
      entry: resolve(pluginRoot, 'index.js'),
      name: 'CpaVideoWorldPlugin',
      formats: ['iife'],
      fileName: () => 'video-world.iife.js',
    },
    rollupOptions: {
      external: ['vue', 'element-plus', '@element-plus/icons-vue'],
      output: {
        globals: {
          vue: 'Vue',
          'element-plus': 'ElementPlus',
          '@element-plus/icons-vue': 'ElementPlusIconsVue',
        },
        assetFileNames: 'video-world.[ext]',
      },
    },
  },
})
