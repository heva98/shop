import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/** Writes asset-list.json: every script and stylesheet the build produced.
 * The service worker (public/sw.js) saves them all, so screens that load
 * on demand still open with no connection. */
function assetList() {
  return {
    name: 'asset-list',
    generateBundle(_options, bundle) {
      const files = Object.keys(bundle).filter((name) => /\.(js|css)$/.test(name)).map((name) => `/${name}`).sort()
      this.emitFile({ type: 'asset', fileName: 'asset-list.json', source: JSON.stringify(files) })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), assetList()],
})
