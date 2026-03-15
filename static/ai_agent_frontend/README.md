# AI Agent Frontend Build Guide

This directory contains the Node/Vite frontend for the AI Agent Builder.

## Requirements

- Node.js `>=18.18.0 <23`
- npm `>=9`

## Install

```bash
npm ci
```

Use `npm ci` on CI/servers for reproducible and faster installs.

## Scripts

- `npm run dev` - start local dev server
- `npm run typecheck` - run TypeScript checks
- `npm run lint` - run ESLint on `src/**/*.{ts,tsx}`
- `npm run build` - production build
- `npm run build:ci` - strict CI build (`typecheck` + `lint` + `build`)
- `npm run preview` - preview built output locally

## Output Contract

Build output is generated into:

- `dist/index.html`
- `dist/assets/ai-agent.js` (stable entry filename kept for backend compatibility)

Additional vendor chunks and assets are hashed for better cache behavior.

## Troubleshooting

- If build fails with dependency mismatch, delete `node_modules` and run `npm ci`.
- If lint fails on old files, fix the reported issues before deploy to keep CI clean.
