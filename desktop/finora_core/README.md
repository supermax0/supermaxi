# FINORA CORE — Desktop

Tauri 2 + React 18 + TypeScript (strict) control center for FINORA CORE. Architecture: `docs/finora-core-architecture.md`.

## Commands

```bash
npm install
npm run dev          # web shell at http://localhost:5174 (development data)
npm run verify       # format check, lint, typecheck, unit + component tests, production build
npm run e2e          # Playwright (installed Microsoft Edge), incl. visual regression at 5 resolutions
npm run e2e:live     # against a real local server — see "Live backend" below
npm run e2e:settings # settings workflow with intercepted APIs; no real Meta messages
npm run tauri build  # Windows installer (NSIS; WiX/MSI fails on non-ASCII paths) in src-tauri/target/release/bundle
```

## Data sources

| Build | Source |
|---|---|
| `npm run dev`, or `VITE_FINORA_DEV_DATA=1` | `DevDataSource` — in-memory development data, visible **DEV DATA** badge |
| production, or `VITE_FINORA_SOURCE=http` | `HttpDataSource` — server setup → sign-in → live data over REST + SSE; never falls back to demo data |

Development URL parameters (dev data only): `sim=0` (no scripted agent activity), `cycle=N` / `cycleDelay=ms` (start a scripted scenario: 0 = new lead, 1 = clinic question, 2 = approval request), `frozen=<ISO date>` (fixed clock), `latency=ms`, `gl=0` (force the static orb fallback).

## Live backend (Phase 6)

```bash
py scripts/provision_finora_core_e2e.py setup <creds.json>      # from the repo root; dev only, random credentials
# start a server: FINORA_CORE_HOUSE_TENANT=fc-e2e-house FINORA_CORE_DEV_LOOPBACK=1 FINORA_ENV=development
#   FLASK_PORT=5018 FINORA_CORE_ALLOWED_ORIGINS=http://localhost:5175 python app.py
FC_E2E_CREDS=<creds.json> npm run e2e:live
py scripts/provision_finora_core_e2e.py cleanup
```

To use the dev server against a backend manually: `VITE_FINORA_SOURCE=http VITE_FINORA_API_URL=http://127.0.0.1:5018 npm run dev`.
Production builds always use the HTTP source: first run asks for the server URL (https only, except localhost), then sign-in.

Windows remembers sign-in across app restarts using a DPAPI-encrypted session in the app's local data directory.
It stores session tokens only, bound to the selected server and Windows user; passwords are never saved.
Refresh tokens rotate automatically and expire after 14 days without renewal. Signing out deletes the saved session.
The browser preview keeps its existing tab-scoped session storage.

## Meta, AI and customer responses

Super Admin settings now include Meta connection/synchronization, cloud OpenAI and local Ollama providers,
encrypted Core-specific cloud keys, response language/style, review/manual/automatic modes and a safe reply preview.
See [the Arabic setup guide](../../docs/finora-core-settings.md). Update the FINORA server alongside the desktop app.

Photos, videos and voice recordings now have review-before-send, authenticated previews and saved AI analysis.
See [the Arabic media guide](../../docs/finora-core-media.md) for supported formats, local/cloud capabilities and server setup.

## Performance notes

- The orb is one GPU shader pass per layer; the CPU only advances phases and lerps state parameters. The render loop stops while the workspace is open or the window is hidden; reduced motion renders a single static frame.
- The orb→workspace morph scales an **empty** glass shell (`layoutId="core-surface"`), never the content.
- Workspace content is mounted at startup and kept rasterized (opacity 0.001, not 0: Chrome skips rasterizing fully transparent subtrees). Each column has its own compositor layer, so the intro slide never repaints text.
- Measured on Intel UHD (D3D11): one ~48ms first frame after the click, then 7–14ms frames for the whole morph.
- Messages render the latest 60 and load older ones on demand.

## Layout and RTL

The workspace is fully RTL (logical CSS properties): conversations on the start (right) side, customer profile on the end side, customer messages at the start, outgoing messages at the end. The titlebar and the orb stage use physical positions on purpose (Windows window controls; Instagram left / Facebook right).
