# Bank of America — SAP → Oracle Fusion Migration Demo

A standalone, self-contained **React + Vite** demo (no backend) that mocks a Bank of
America SAP → Oracle Fusion data migration. It walks each SAP object through a full
migration wizard and visualizes the end-to-end pipeline as an **interactive, actionable
architecture diagram** whose stage nodes show live status and can jump into — or run —
the corresponding migration step.

## Run locally

```bash
npm install
npm run dev
```

Then open the printed URL (default **http://localhost:5173/**).

Other scripts:

```bash
npm run build     # production build
npm run preview   # preview the production build
node scripts/generate-sample-data.js   # regenerate the sample CSVs under public/sample-data/
```

## What's included

- **Bank of America branding** — logo at `public/assets/bank-of-america-logo.svg`
  (placeholder SVG; drop in `bank-of-america-logo.png` to replace) and the red
  `#E31837` / navy `#012169` theme, on every page.
- **Routing** (`react-router-dom`) between a **Migration** workspace and an
  **Architecture** page.
- **All SAP objects** — Customers/Business Partners, Vendors/Suppliers, GL Accounts,
  Materials/Items, Cost Centers, Fixed Assets, Journals/Balances. Each has:
  - a downloadable sample CSV under `public/sample-data/`, and
  - a SAP-field → Oracle-Fusion-field mapping config (see
    `src/config/migrationObjects.js`).
- **Migration wizard** (per object): Download Sample File → Upload / Load Sample Data →
  Validate → Transform & Preview → Migrate (animated progress) → Reconcile & Download
  Migrated Output. Everything is **dynamic** — every count, table, and status reflects
  the data actually loaded/transformed.

## Interactive Architecture page

The Architecture page (`/architecture`) is a live dashboard of the migration, not a
static diagram:

- **Clickable flow diagram** — the pipeline is rendered as connected stage nodes:
  `SAP Source → Extract → Staging → Field Mapping/Transformation → Validation/Data
  Quality → Load to Oracle Fusion (FBDI) → Reconciliation/Summary`. High-contrast on
  white (navy headings, red accents), no colored fills behind text.
- **Live status badges** — each node shows a dynamic badge (Not started / In progress /
  Completed / Errors) plus a compact live count (e.g. "3 of 7 objects loaded",
  "12 errors across 2 objects", "2 loaded, 1 with errors") computed from the shared
  migration state. Badges update as you run steps from either page.
- **Actionable detail drawer** — clicking any node opens a side drawer with a
  plain-language description, the stage's inputs/outputs, the SAP objects/fields
  involved, and the current live status (aggregate + per-object). Each drawer has:
  - an action button that **navigates into the Migration wizard at the matching step**
    for the currently selected object (e.g. the Validation node routes to the validate
    step, the Load node to the migrate step), and
  - where relevant a **Run** button (Run Validation / Run Transform / Run Migration)
    that executes the exact same store handler used by the wizard and reflects the
    updated status back on the diagram.
- **Per-object status table** — a compact table listing each SAP object and which
  stages it has passed, with click-through into that object's wizard.

## Shared state

A single [Zustand](https://github.com/pmndrs/zustand) store
(`src/store/migrationStore.js`) holds, per SAP object: loaded source records, validation
results/errors, transform output, and migration status/summary. Both the Migration
workspace and the Architecture page read from and write to this store, so counts and
statuses stay in sync across pages. The selected object and current wizard step are also
encoded in the URL (`/migration/:step?object=<id>`) to support deep-linking from the
Architecture page.

## Project layout

```
sap-to-oracle-fusion-migration-demo/
├─ public/
│  ├─ assets/bank-of-america-logo.svg
│  └─ sample-data/*.csv            # one sample extract per SAP object
├─ scripts/generate-sample-data.js # regenerates the sample CSVs from the config
├─ src/
│  ├─ config/migrationObjects.js    # SAP objects, field mappings, sample rows
│  ├─ config/pipeline.js            # wizard steps + interactive pipeline stages
│  ├─ store/migrationStore.js       # shared Zustand migration state + selectors
│  ├─ utils/{transforms,csv}.js     # field transforms + CSV parse/generate/download
│  ├─ components/StatusBadge.jsx
│  ├─ pages/MigrationPage.jsx       # the wizard workspace
│  └─ pages/ArchitecturePage.jsx    # the interactive architecture page
└─ index.html
```
