import { Fragment, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { MIGRATION_OBJECTS, getObject } from '../config/migrationObjects'
import { PIPELINE_STAGES } from '../config/pipeline'
import {
  STATUS,
  aggregateStageStatus,
  objectStageStatus,
  useMigrationStore,
} from '../store/migrationStore'
import StatusBadge from '../components/StatusBadge.jsx'

// Interactive, actionable Architecture page.
// - The migration flow is rendered as connected, clickable stage nodes.
// - Each node shows a LIVE aggregate status badge computed from the shared store.
// - Clicking a node opens a details drawer with description, I/O, involved SAP
//   objects/fields, live per-stage status, and action buttons that either navigate
//   into the Migration wizard at the matching step or run the step's handler directly.
// - A per-object status table lets you click through into any object's wizard.
export default function ArchitecturePage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const objects = useMigrationStore((s) => s.objects)
  const validate = useMigrationStore((s) => s.validate)
  const transform = useMigrationStore((s) => s.transform)
  const migrate = useMigrationStore((s) => s.migrate)
  const [openStage, setOpenStage] = useState(null)

  const selectedId = searchParams.get('object') || MIGRATION_OBJECTS[0].id
  const selected = getObject(selectedId) || MIGRATION_OBJECTS[0]

  const selectObject = (id) => {
    const params = new URLSearchParams(searchParams)
    params.set('object', id)
    setSearchParams(params)
  }

  // Navigate into the wizard at a given step for the currently selected object.
  const goToStep = (wizardStep, objectId = selectedId) => {
    navigate(`/migration/${wizardStep}?object=${objectId}`)
  }

  // Run a stage's handler directly from the Architecture page for the selected object.
  const runStage = async (action) => {
    if (action === 'validate') validate(selectedId)
    else if (action === 'transform') transform(selectedId)
    else if (action === 'migrate') await migrate(selectedId)
  }

  return (
    <div className="page">
      <h1>Migration Architecture</h1>
      <p className="subtitle">
        End-to-end SAP &rarr; Oracle Fusion flow. Click any stage for live status and actions.
      </p>

      {/* Legend */}
      <div className="legend">
        <StatusBadge status={STATUS.NOT_STARTED} />
        <StatusBadge status={STATUS.IN_PROGRESS} />
        <StatusBadge status={STATUS.COMPLETED} />
        <StatusBadge status={STATUS.ERRORS} />
      </div>

      {/* Selected object context (drives the action buttons in each stage panel) */}
      <div className="card">
        <strong style={{ color: 'var(--boa-navy)' }}>Selected object for actions:</strong>
        <div className="obj-select" style={{ marginTop: 10, marginBottom: 0 }}>
          {MIGRATION_OBJECTS.map((o) => (
            <button key={o.id} className={o.id === selected.id ? 'active' : ''} onClick={() => selectObject(o.id)}>
              <span className="obj-name">{o.label}</span>
              <span className="obj-sub">{objects[o.id].loaded ? `${objects[o.id].sourceRows.length} records` : 'not loaded'}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Interactive flow diagram */}
      <div className="flow">
        {PIPELINE_STAGES.map((stage, i) => {
          const agg = aggregateStageStatus(objects, stage.statusKey)
          return (
            <Fragment key={stage.key}>
              <button
                className={`flow-node ${openStage === stage.key ? 'selected' : ''}`}
                onClick={() => setOpenStage(stage.key)}
              >
                <span className="node-title">{stage.title}</span>
                <StatusBadge status={agg} />
                <span className="node-status">{liveStatusText(stage, objects)}</span>
              </button>
              {i < PIPELINE_STAGES.length - 1 && <span className="flow-arrow">&rarr;</span>}
            </Fragment>
          )
        })}
      </div>

      {/* Per-object status table with click-through into each object's wizard */}
      <div className="card">
        <h2>Per-object status</h2>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>SAP object</th>
                <th>Extract</th>
                <th>Mapping</th>
                <th>Validation</th>
                <th>Transform</th>
                <th>Load</th>
                <th>Open</th>
              </tr>
            </thead>
            <tbody>
              {MIGRATION_OBJECTS.map((o) => {
                const ss = objectStageStatus(objects[o.id])
                return (
                  <tr key={o.id}>
                    <td>{o.label}</td>
                    <td><StatusBadge status={ss.extract} /></td>
                    <td><StatusBadge status={ss.mapping} /></td>
                    <td><StatusBadge status={ss.validation} /></td>
                    <td><StatusBadge status={ss.transform} /></td>
                    <td><StatusBadge status={ss.load} /></td>
                    <td><button className="btn small" onClick={() => goToStep('load', o.id)}>Open wizard</button></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {openStage && (
        <StageDrawer
          stage={PIPELINE_STAGES.find((s) => s.key === openStage)}
          selected={selected}
          objects={objects}
          onClose={() => setOpenStage(null)}
          onGoToStep={goToStep}
          onRun={runStage}
          onSelectObject={selectObject}
        />
      )}
    </div>
  )
}

// Build the compact live-status line shown under each node.
function liveStatusText(stage, objects) {
  const total = MIGRATION_OBJECTS.length
  if (stage.statusKey === 'extract') {
    const loaded = MIGRATION_OBJECTS.filter((o) => objects[o.id].loaded).length
    return `${loaded} of ${total} objects loaded`
  }
  if (stage.statusKey === 'validation') {
    const withErrors = MIGRATION_OBJECTS.filter((o) => objects[o.id].validation.errorCount > 0)
    const totalErrors = MIGRATION_OBJECTS.reduce((n, o) => n + objects[o.id].validation.errorCount, 0)
    const ran = MIGRATION_OBJECTS.filter((o) => objects[o.id].validation.ran).length
    if (totalErrors > 0) return `${totalErrors} errors across ${withErrors.length} object(s)`
    return `${ran} of ${total} objects validated`
  }
  if (stage.statusKey === 'transform') {
    const done = MIGRATION_OBJECTS.filter((o) => objects[o.id].transform.ran).length
    return `${done} of ${total} objects transformed`
  }
  if (stage.statusKey === 'load') {
    const done = MIGRATION_OBJECTS.filter((o) => objects[o.id].migration.status === STATUS.COMPLETED).length
    const err = MIGRATION_OBJECTS.filter((o) => objects[o.id].migration.status === STATUS.ERRORS).length
    return `${done} loaded${err ? `, ${err} with errors` : ''}`
  }
  return ''
}

// Side drawer with actionable details for a single stage.
function StageDrawer({ stage, selected, objects, onClose, onGoToStep, onRun, onSelectObject }) {
  const [running, setRunning] = useState(false)
  const selState = objects[selected.id]
  const stageStatusForSelected = objectStageStatus(selState)[stage.statusKey]

  const handleRun = async () => {
    setRunning(true)
    await onRun(stage.runAction)
    setRunning(false)
  }

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={stage.title}>
        <div className="drawer-head">
          <h2>{stage.title}</h2>
          <button className="close" onClick={onClose} aria-label="Close">&times;</button>
        </div>
        <div className="drawer-body">
          <p>{stage.description}</p>

          <h3>Inputs &amp; Outputs</h3>
          <dl className="kv">
            <dt>Inputs</dt><dd>{stage.inputs}</dd>
            <dt>Outputs</dt><dd>{stage.outputs}</dd>
          </dl>

          <h3>Live status (all objects)</h3>
          <p><StatusBadge status={aggregateStageStatus(objects, stage.statusKey)} /> &nbsp; {liveStatusText(stage, objects)}</p>
          <ul style={{ paddingLeft: 18, margin: '6px 0' }}>
            {MIGRATION_OBJECTS.map((o) => (
              <li key={o.id} style={{ marginBottom: 4 }}>
                {o.label}: <StatusBadge status={objectStageStatus(objects[o.id])[stage.statusKey]} />
              </li>
            ))}
          </ul>

          <h3>Selected object: {selected.label}</h3>
          <p className="hint">Actions below apply to the selected object (change it on the page or below).</p>
          <dl className="kv">
            <dt>SAP source</dt><dd className="mono">{selected.sapTable}</dd>
            <dt>Oracle target</dt><dd>{selected.oracleTarget}</dd>
            <dt>Status</dt><dd><StatusBadge status={stageStatusForSelected} /></dd>
          </dl>

          <h4 style={{ marginBottom: 4, color: 'var(--boa-navy)' }}>SAP fields involved</h4>
          <div className="chip-row">
            {selected.fields.map((f) => (
              <span key={f.sap} className="chip" title={`${f.sap} → ${f.oracle}`}>{f.sap} &rarr; {f.oracle}</span>
            ))}
          </div>

          <h4 style={{ marginTop: 16, marginBottom: 6, color: 'var(--boa-navy)' }}>Switch selected object</h4>
          <div className="chip-row">
            {MIGRATION_OBJECTS.map((o) => (
              <span
                key={o.id}
                className="chip"
                style={o.id === selected.id ? { borderColor: 'var(--boa-red)', fontWeight: 700 } : undefined}
                onClick={() => onSelectObject(o.id)}
              >
                {o.label}
              </span>
            ))}
          </div>

          <h3>Actions</h3>
          <div className="row-actions">
            <button className="btn" onClick={() => onGoToStep(stage.wizardStep)}>
              {stage.actionLabel}
            </button>
            {stage.runAction && (
              <button className="btn secondary" disabled={!selState.loaded || running} onClick={handleRun}>
                {running ? 'Running…' : stage.runLabel}
              </button>
            )}
          </div>
          {stage.runAction && !selState.loaded && (
            <p className="hint">Load data for {selected.label} first (Extract / Load step).</p>
          )}
        </div>
      </aside>
    </>
  )
}
