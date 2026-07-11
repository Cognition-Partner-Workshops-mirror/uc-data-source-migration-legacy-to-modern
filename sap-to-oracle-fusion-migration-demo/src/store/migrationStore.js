// Shared migration state (Zustand store).
//
// This single store is the source of truth for BOTH the Migration workspace and the
// interactive Architecture page. It holds, per SAP object: the loaded source records,
// validation results/errors, the transformed (Oracle Fusion) output, and the migration
// status/summary. Any component can read counts/statuses and trigger the same handlers,
// so the diagram badges and the wizard always stay in sync.

import { create } from 'zustand'
import { MIGRATION_OBJECTS, getObject } from '../config/migrationObjects'
import { applyTransform } from '../utils/transforms'

// Status enum shared across stages.
export const STATUS = {
  NOT_STARTED: 'not_started',
  IN_PROGRESS: 'in_progress',
  COMPLETED: 'completed',
  ERRORS: 'errors',
}

// Build the empty per-object slice.
function emptyObjectState() {
  return {
    sourceRows: [],
    loaded: false,
    validation: { ran: false, errors: [], validCount: 0, errorCount: 0 },
    transform: { ran: false, output: [] },
    migration: { status: STATUS.NOT_STARTED, progress: 0, migratedCount: 0, failedCount: 0, summary: '' },
  }
}

function initialObjects() {
  const obj = {}
  for (const def of MIGRATION_OBJECTS) obj[def.id] = emptyObjectState()
  return obj
}

// Run declarative validation rules derived from the field config.
function runValidation(def, rows) {
  const errors = []
  rows.forEach((row, idx) => {
    for (const f of def.fields) {
      const raw = row[f.sap]
      const val = String(raw ?? '').trim()
      if (f.required && val === '') {
        errors.push({ row: idx + 1, field: f.sap, oracle: f.oracle, message: `Required field "${f.oracle}" is empty` })
        continue
      }
      if (val === '') continue
      if (f.sapType === 'number' && applyTransform('toNumber', val) === '') {
        errors.push({ row: idx + 1, field: f.sap, oracle: f.oracle, message: `"${val}" is not a valid number for "${f.oracle}"` })
      }
      if (f.sapType === 'date' && applyTransform('dateISO', val) === '') {
        errors.push({ row: idx + 1, field: f.sap, oracle: f.oracle, message: `"${val}" is not a valid date (expected YYYYMMDD) for "${f.oracle}"` })
      }
    }
  })
  const errorRows = new Set(errors.map((e) => e.row))
  return { ran: true, errors, validCount: rows.length - errorRows.size, errorCount: errors.length }
}

// Rows -> Oracle Fusion output objects using each field's transform.
function transformRows(def, rows) {
  return rows.map((row) => {
    const out = {}
    for (const f of def.fields) out[f.oracle] = applyTransform(f.transform, row[f.sap])
    return out
  })
}

export const useMigrationStore = create((set, get) => ({
  objects: initialObjects(),

  // Load records into an object (used by both file upload and "Load Sample Data").
  loadRows: (id, rows) =>
    set((state) => ({
      objects: {
        ...state.objects,
        [id]: { ...emptyObjectState(), sourceRows: rows, loaded: rows.length > 0 },
      },
    })),

  // Load the built-in sample rows for an object.
  loadSample: (id) => {
    const def = getObject(id)
    if (def) get().loadRows(id, def.sample.map((r) => ({ ...r })))
  },

  // Run validation for an object; stores errors + counts.
  validate: (id) => {
    const def = getObject(id)
    const st = get().objects[id]
    if (!def || !st.loaded) return
    const validation = runValidation(def, st.sourceRows)
    set((state) => ({ objects: { ...state.objects, [id]: { ...state.objects[id], validation } } }))
    return validation
  },

  // Transform an object's rows into Oracle Fusion output (auto-validates first).
  transform: (id) => {
    const def = getObject(id)
    const st = get().objects[id]
    if (!def || !st.loaded) return
    if (!st.validation.ran) get().validate(id)
    const output = transformRows(def, get().objects[id].sourceRows)
    set((state) => ({ objects: { ...state.objects, [id]: { ...state.objects[id], transform: { ran: true, output } } } }))
    return output
  },

  // Run the animated migration. Returns a Promise that resolves when complete.
  migrate: (id) => {
    const def = getObject(id)
    const st = get().objects[id]
    if (!def || !st.loaded) return Promise.resolve()
    // Ensure validation + transform have run so counts are accurate.
    if (!get().objects[id].validation.ran) get().validate(id)
    if (!get().objects[id].transform.ran) get().transform(id)

    const validation = get().objects[id].validation
    const total = get().objects[id].sourceRows.length
    const migratedCount = validation.validCount
    const failedCount = total - migratedCount

    set((state) => ({
      objects: {
        ...state.objects,
        [id]: { ...state.objects[id], migration: { ...state.objects[id].migration, status: STATUS.IN_PROGRESS, progress: 0 } },
      },
    }))

    return new Promise((resolve) => {
      let progress = 0
      const timer = setInterval(() => {
        progress = Math.min(100, progress + 10)
        set((state) => ({
          objects: {
            ...state.objects,
            [id]: { ...state.objects[id], migration: { ...state.objects[id].migration, progress } },
          },
        }))
        if (progress >= 100) {
          clearInterval(timer)
          const status = failedCount > 0 ? STATUS.ERRORS : STATUS.COMPLETED
          const summary =
            failedCount > 0
              ? `Loaded ${migratedCount}/${total} records to Oracle Fusion; ${failedCount} rejected during validation.`
              : `Loaded all ${migratedCount} records to Oracle Fusion successfully.`
          set((state) => ({
            objects: {
              ...state.objects,
              [id]: {
                ...state.objects[id],
                migration: { status, progress: 100, migratedCount, failedCount, summary },
              },
            },
          }))
          resolve({ status, migratedCount, failedCount, summary })
        }
      }, 120)
    })
  },

  // Reset a single object back to its empty state.
  resetObject: (id) =>
    set((state) => ({ objects: { ...state.objects, [id]: emptyObjectState() } })),

  // Reset everything.
  resetAll: () => set({ objects: initialObjects() }),
}))

// ---- Derived selectors (used by the Architecture diagram for live status) ----

// Per-object stage status map. Stages: extract, mapping, validation, transform, load.
export function objectStageStatus(objState) {
  const extract = objState.loaded ? STATUS.COMPLETED : STATUS.NOT_STARTED
  const mapping = objState.loaded ? STATUS.COMPLETED : STATUS.NOT_STARTED
  let validation = STATUS.NOT_STARTED
  if (objState.validation.ran) validation = objState.validation.errorCount > 0 ? STATUS.ERRORS : STATUS.COMPLETED
  const transform = objState.transform.ran ? STATUS.COMPLETED : STATUS.NOT_STARTED
  const load = objState.migration.status
  return { extract, mapping, validation, transform, load }
}

// Aggregate a stage's status across all objects (for the flow-diagram badge).
export function aggregateStageStatus(objectsState, stageKey) {
  const statuses = MIGRATION_OBJECTS.map((d) => objectStageStatus(objectsState[d.id])[stageKey])
  if (statuses.some((s) => s === STATUS.ERRORS)) return STATUS.ERRORS
  if (statuses.some((s) => s === STATUS.IN_PROGRESS)) return STATUS.IN_PROGRESS
  if (statuses.every((s) => s === STATUS.COMPLETED)) return STATUS.COMPLETED
  if (statuses.some((s) => s === STATUS.COMPLETED)) return STATUS.IN_PROGRESS
  return STATUS.NOT_STARTED
}
