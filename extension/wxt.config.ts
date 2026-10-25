import { defineConfig } from 'wxt';

// See https://wxt.dev/api/reference/wxt/interfaces/inlineconfig.html
export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  // WXT already skips its build folder, but by full path, which a folder named like
  // "CalHack13.0(1)" breaks: the dev server then sees its own sidepanel.html and reloads forever
  watchOptions: { ignored: ['**/.output/**'] },
  manifest: {
    name: 'gomdori',
    description: 'Scores Amazon products against the rest of your setup.',
    // The toolbar icon; clicking it opens the side panel (see background.ts)
    action: {},
    // Keeps the plan and setup when the side panel closes (see utils/storage.ts)
    permissions: ['storage'],
    // The server runs locally (see docs/api-contract.md)
    host_permissions: ['http://127.0.0.1:8000/*'],
  },
});
