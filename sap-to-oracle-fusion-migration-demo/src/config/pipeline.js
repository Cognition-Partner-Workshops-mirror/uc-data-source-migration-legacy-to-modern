// Definition of the end-to-end migration pipeline.
//
// WIZARD_STEPS drives the Migration workspace wizard (ordered).
// PIPELINE_STAGES drives the interactive Architecture flow diagram. Each stage links
// to a wizard step (for deep-link navigation), a status key (read from the shared store
// via objectStageStatus), and optionally a runnable action executed directly from the
// Architecture page using the exact same store handler as the wizard.

// Ordered wizard steps. `key` is used for deep-linking (/migration/:step).
export const WIZARD_STEPS = [
  { key: 'source', label: 'Source & Sample' },
  { key: 'load', label: 'Extract / Load' },
  { key: 'validate', label: 'Validate' },
  { key: 'transform', label: 'Transform & Preview' },
  { key: 'migrate', label: 'Migrate' },
  { key: 'output', label: 'Reconcile & Output' },
]

export function stepIndex(key) {
  const i = WIZARD_STEPS.findIndex((s) => s.key === key)
  return i < 0 ? 0 : i
}

// Interactive flow-diagram stages.
export const PIPELINE_STAGES = [
  {
    key: 'source',
    title: 'SAP Source Systems / Objects',
    statusKey: 'extract',
    wizardStep: 'source',
    description:
      'The legacy SAP ECC/S4 environment holding the master and transactional data to be migrated (KNA1, LFA1, SKA1, MARA, CSKS, ANLA, BKPF/BSEG).',
    inputs: 'SAP master & transactional tables',
    outputs: 'Selected SAP object + downloadable sample extract (CSV)',
    actionLabel: 'Open object & download sample',
  },
  {
    key: 'extract',
    title: 'Extract',
    statusKey: 'extract',
    wizardStep: 'load',
    description:
      'Records are extracted from SAP (or uploaded as a CSV extract) into the migration tool. In this demo you upload a CSV or click "Load Sample Data".',
    inputs: 'SAP extract CSV (upload or sample)',
    outputs: 'Raw source records loaded into the tool',
    actionLabel: 'Go to Extract / Load step',
  },
  {
    key: 'staging',
    title: 'Staging',
    statusKey: 'extract',
    wizardStep: 'load',
    description:
      'Loaded records are held in a staging area where they can be inspected before transformation. Row counts here reflect exactly what was loaded.',
    inputs: 'Raw source records',
    outputs: 'Staged records ready for mapping',
    actionLabel: 'View staged records',
  },
  {
    key: 'mapping',
    title: 'Field Mapping / Transformation',
    statusKey: 'transform',
    wizardStep: 'transform',
    runAction: 'transform',
    description:
      'Each SAP field is mapped to its Oracle Fusion target field and transformed (e.g. YYYYMMDD dates to ISO, code lookups, numeric coercion). Produces the Fusion-ready output preview.',
    inputs: 'Staged SAP records + field mapping config',
    outputs: 'Transformed Oracle Fusion records (preview)',
    actionLabel: 'Go to Transform step',
    runLabel: 'Run Transform',
  },
  {
    key: 'validation',
    title: 'Validation / Data Quality',
    statusKey: 'validation',
    wizardStep: 'validate',
    runAction: 'validate',
    description:
      'Data-quality rules run against the source records: required fields present, numeric fields parseable, dates well-formed. Errors are reported per row and field.',
    inputs: 'Staged SAP records + validation rules',
    outputs: 'Valid record set + list of data-quality errors',
    actionLabel: 'Go to Validate step',
    runLabel: 'Run Validation',
  },
  {
    key: 'load',
    title: 'Load to Oracle Fusion (FBDI / Import)',
    statusKey: 'load',
    wizardStep: 'migrate',
    runAction: 'migrate',
    description:
      'Valid, transformed records are loaded into Oracle Fusion via the appropriate FBDI template / import. Progress is shown live and rejected rows are reported.',
    inputs: 'Valid transformed records',
    outputs: 'Records loaded into Oracle Fusion + load summary',
    actionLabel: 'Go to Migrate step',
    runLabel: 'Run Migration',
  },
  {
    key: 'reconciliation',
    title: 'Reconciliation / Summary',
    statusKey: 'load',
    wizardStep: 'output',
    description:
      'Source vs. loaded counts are reconciled and a migration summary is produced. The transformed Oracle Fusion output can be downloaded as CSV.',
    inputs: 'Load results + source counts',
    outputs: 'Reconciliation summary + downloadable migrated output CSV',
    actionLabel: 'View reconciliation & download output',
  },
]
