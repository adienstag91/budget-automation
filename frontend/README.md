# Budget Pivot Frontend

An Excel/GSheet-style pivot table for your budget data. Built with React +
Vite + AG Grid. Talks to the FastAPI backend (`../api.py`).

## What it does

- **Pivot table**: Category rows that expand into Subcategory rows, with
  months as columns and a Total column.
- **Grand total row** pinned at the bottom, per month.
- **Drilldown**: Click any subcategory row to see the individual charges that
  make it up (date, merchant, amount, notes).
- **Recategorize**: From the drilldown, change a transaction's category /
  subcategory and save. The pivot refreshes automatically.
- **Month range**: Choose last 3 / 6 / 12 / 24 months.

## Running it

You need two things running: the backend API and this frontend.

### 1. Start the backend (from the project root, not this folder)

```bash
# Make sure the database is up first:
docker-compose up -d

# Then start the API:
uvicorn api:app --reload --port 8000
```

### 2. Start this frontend

```bash
cd frontend
npm install        # only needed the first time
npm run dev
```

Then open the URL it prints (usually http://localhost:5173).

## How it connects

The dev server proxies any request to `/api/*` to `http://localhost:8000`
(see `vite.config.js`). So the frontend never hardcodes the backend URL and
there are no CORS issues during development.

## Project files

- `src/api.js` – all backend calls in one place
- `src/App.jsx` – top-level layout, toolbar, month selector
- `src/PivotGrid.jsx` – the AG Grid pivot table (tree rows + month columns)
- `src/Drilldown.jsx` – the transaction panel + recategorize controls

## Hosting later (free)

To stop paying for a hosted frontend, this can be deployed free on
Vercel/Netlify/Cloudflare Pages. That requires pointing it at a deployed
backend instead of localhost — ask Claude to set that up when you're ready.
