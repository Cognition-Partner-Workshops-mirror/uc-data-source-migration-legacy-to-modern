import { STATUS } from '../store/migrationStore'

// Small colored status pill reused on the diagram, per-object table, and wizard.
const LABELS = {
  [STATUS.NOT_STARTED]: 'Not started',
  [STATUS.IN_PROGRESS]: 'In progress',
  [STATUS.COMPLETED]: 'Completed',
  [STATUS.ERRORS]: 'Errors',
}

export default function StatusBadge({ status, label }) {
  const cls = status || STATUS.NOT_STARTED
  return (
    <span className={`badge ${cls}`}>
      <span className="dot" />
      {label || LABELS[cls]}
    </span>
  )
}
