import { defineConfig } from 'vite'
import { resolve } from 'path'

export default defineConfig({
  build: {
    outDir: 'app/static/dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: resolve(__dirname, 'app/static/js/main.js')
      },
      output: {
        entryFileNames: 'js/[name].js',
        assetFileNames: 'assets/[name][extname]'
      }
    }
  }
})
