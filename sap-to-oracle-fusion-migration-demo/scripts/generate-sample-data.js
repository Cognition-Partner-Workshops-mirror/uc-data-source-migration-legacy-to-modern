// Generates the downloadable sample CSVs under public/sample-data/ from the single
// source of truth in src/config/migrationObjects.js, keeping them consistent with the
// in-app "Load Sample Data" action. Run with: node scripts/generate-sample-data.js
import { writeFileSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import Papa from 'papaparse'
import { MIGRATION_OBJECTS } from '../src/config/migrationObjects.js'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(here, '../public/sample-data')
mkdirSync(outDir, { recursive: true })

for (const def of MIGRATION_OBJECTS) {
  const headers = def.fields.map((f) => f.sap)
  const csv = Papa.unparse({ fields: headers, data: def.sample.map((r) => headers.map((h) => r[h] ?? '')) })
  const file = resolve(outDir, `${def.id}_sample.csv`)
  writeFileSync(file, csv + '\n', 'utf8')
  console.log(`wrote ${file} (${def.sample.length} rows)`)
}
