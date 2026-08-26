# IncidentIQ — web

Next.js (App Router) + TypeScript + Tailwind frontend.

```bash
npm install
npm run dev        # http://localhost:3000
npm run typecheck
npm run lint
npm run build
```

The backend base URL comes from `NEXT_PUBLIC_API_BASE_URL` (see `.env.example`); it
defaults to `http://localhost:8001`. Run the API from `apps/api` — see the
[root README](../../README.md).
