# Catalyst dashboard frontend (M1)

React 18 + Vite + TypeScript. Read-only SHFFT episode roster (D1, D9 partial).

## Run

Requires the API running on port 8000 (see repo root `README.md`).

```bash
npm install
npm run dev        # http://localhost:5173 (proxies /api → :8000)
```

`npm run build` type-checks and produces a production bundle in `dist/`.

## What it shows

- One row per SHFFT anchor episode: patient, admit → discharge, procedure,
  MS-DRG, disposition chip, days left in the 30-day window, status.
- Status is `active` / `completed` relative to the as-of clock.
  Episodes with admit after as-of (`upcoming`) are omitted from the demo roster.
- Header shows the resolved as-of date and whether it is frozen demo or live
  today, plus a synthetic-data tag.
