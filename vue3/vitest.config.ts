import {fileURLToPath, URL} from 'node:url'

import {defineConfig} from 'vitest/config'

// Deliberately standalone instead of extending vite.config.ts: the unit tests cover plain
// TypeScript modules, so they need the "@" alias and nothing else. Loading the app's plugin
// chain (vuetify, PWA, locale coverage) would only make the suite slower and more fragile.
export default defineConfig({
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url)),
        },
    },
    test: {
        environment: 'node',
        include: ['src/**/*.spec.ts'],
    },
})
