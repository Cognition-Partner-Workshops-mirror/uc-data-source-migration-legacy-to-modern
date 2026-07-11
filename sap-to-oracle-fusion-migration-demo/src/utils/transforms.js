// Field-level transform functions applied when converting a SAP source value
// into its Oracle Fusion target value. The transform key is declared per field
// in migrationObjects.js. Each returns a string suitable for the FBDI output.

const ACCOUNT_TYPE = { ASST: 'Asset', LIAB: 'Liability', REV: 'Revenue', EXP: 'Expense', EQTY: 'Owner Equity' }
const ITEM_CLASS = { ROH: 'Raw Material', HAWA: 'Trading Good', FERT: 'Finished Good', VERP: 'Packaging' }
const ASSET_CATEGORY = { '2000': 'FURNITURE-OFFICE', '3000': 'COMPUTER-HARDWARE', '4000': 'VEHICLES-FLEET' }

// Convert SAP date (YYYYMMDD) to ISO (YYYY-MM-DD). Returns '' when not parseable.
function toISODate(raw) {
  const v = String(raw ?? '').trim()
  if (!/^\d{8}$/.test(v)) return ''
  return `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6, 8)}`
}

export const TRANSFORMS = {
  direct: (v) => String(v ?? ''),
  trim: (v) => String(v ?? '').trim(),
  upper: (v) => String(v ?? '').trim().toUpperCase(),
  lower: (v) => String(v ?? '').trim().toLowerCase(),
  toNumber: (v) => {
    const n = Number(String(v ?? '').replace(/,/g, '').trim())
    return Number.isFinite(n) ? String(n) : ''
  },
  dateISO: (v) => toISODate(v),
  accountType: (v) => ACCOUNT_TYPE[String(v ?? '').trim().toUpperCase()] ?? String(v ?? '').trim(),
  itemClass: (v) => ITEM_CLASS[String(v ?? '').trim().toUpperCase()] ?? String(v ?? '').trim(),
  assetCategory: (v) => ASSET_CATEGORY[String(v ?? '').trim()] ?? String(v ?? '').trim(),
  drcr: (v) => {
    const s = String(v ?? '').trim().toUpperCase()
    if (s === 'S') return 'DR'
    if (s === 'H') return 'CR'
    return s
  },
}

export function applyTransform(key, value) {
  const fn = TRANSFORMS[key] || TRANSFORMS.direct
  return fn(value)
}
