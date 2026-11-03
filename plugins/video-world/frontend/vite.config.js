import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'

const frontendNodeModules = resolve(__dirname, '../../../frontend/node_modules')

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      vue: resolve(frontendNodeModules, 'vue'),
      'element-plus': resolve(frontendNodeModules, 'element-plus'),
      '@element-plus/icons-vue': resolve(frontendNodeModules, '@element-plus/icons-vue'),
    },
  },
  build: {
    outDir: resolve(__dirname, 'dist'),
    emptyOutDir: true,
    lib: {
      entry: resolve(__dirname, 'index.js'),
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
