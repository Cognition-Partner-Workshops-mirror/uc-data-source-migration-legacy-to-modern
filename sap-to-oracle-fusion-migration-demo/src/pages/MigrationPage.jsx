import { useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { MIGRATION_OBJECTS, getObject } from '../config/migrationObjects'
import { WIZARD_STEPS, stepIndex } from '../config/pipeline'
import { STATUS, useMigrationStore } from '../store/migrationStore'
import { downloadText, parseCsvFile, rowsToCsv } from '../utils/csv'
import StatusBadge from '../components/StatusBadge.jsx'

// Migration workspace: a step-by-step wizard operating on the currently selected SAP object.
// Both the selected object and the current step are reflected in the URL
// (/migration/:step?object=<id>) so the Architecture page can deep-link into any step.
export default function MigrationPage() {
  const { step: stepParam } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const fileRef = useRef(null)
  const [uploadName, setUploadName] = useState('')

  const objects = useMigrationStore((s) => s.objects)
  const loadSample = useMigrationStore((s) => s.loadSample)
  const loadRows = useMigrationStore((s) => s.loadRows)
  const validate = useMigrationStore((s) => s.validate)
  const transform = useMigrationStore((s) => s.transform)
  const migrate = useMigrationStore((s) => s.migrate)
  const resetObject = useMigrationStore((s) => s.resetObject)

  const objectId = searchParams.get('object') || MIGRATION_OBJECTS[0].id
  const def = getObject(objectId) || MIGRATION_OBJECTS[0]
  const st = objects[def.id]
  const stepKey = WIZARD_STEPS.find((s) => s.key === stepParam)?.key || 'source'

  const goStep = (key) => {
    const params = new URLSearchParams(searchParams)
    params.set('object', def.id)
    navigate(`/migration/${key}?${params.toString()}`)
  }
  const selectObject = (id) => {
    const params = new URLSearchParams(searchParams)
    params.set('object', id)
    setSearchParams(params)
  }

  const headers = useMemo(() => def.fields.map((f) => f.sap), [def])
  const oracleHeaders = useMemo(() => def.fields.map((f) => f.oracle), [def])

  const handleDownloadSample = () => {
    const csv = rowsToCsv(headers, def.sample)
    downloadText(`${def.id}_sample.csv`, csv)
  }
  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadName(file.name)
    const rows = await parseCsvFile(file)
    // Keep only recognised SAP columns so downstream logic stays consistent.
    const cleaned = rows.map((r) => {
      const o = {}
      for (const h of headers) o[h] = r[h] ?? ''
      return o
    })
    loadRows(def.id, cleaned)
  }
  const handleDownloadOutput = () => {
    const output = st.transform.ran ? st.transform.output : transform(def.id)
    downloadText(`${def.id}_oracle_fusion_output.csv`, rowsToCsv(oracleHeaders, output || []))
  }

  const validationBadge = () => {
    if (!st.validation.ran) return STATUS.NOT_STARTED
    return st.validation.errorCount > 0 ? STATUS.ERRORS : STATUS.COMPLETED
  }

  return (
    <div className="page">
      <h1>Migration Workspace</h1>
      <p className="subtitle">
        SAP &rarr; Oracle Fusion mock data migration &mdash; select an object and run it through the wizard.
      </p>

      {/* SAP object selector */}
      <div className="obj-select">
        {MIGRATION_OBJECTS.map((o) => (
          <button
            key={o.id}
            className={o.id === def.id ? 'active' : ''}
            onClick={() => selectObject(o.id)}
          >
            <span className="obj-name">{o.label}</span>
            <span className="obj-sub">{objects[o.id].loaded ? `${objects[o.id].sourceRows.length} records loaded` : 'not loaded'}</span>
          </button>
        ))}
      </div>

      {/* Wizard stepper */}
      <div className="stepper">
        {WIZARD_STEPS.map((s, i) => (
          <button key={s.key} className={s.key === stepKey ? 'active' : ''} onClick={() => goStep(s.key)}>
            <span className="num">{i + 1}</span>
            {s.label}
          </button>
        ))}
      </div>

      <div className="card">
        {stepKey === 'source' && (
          <div>
            <h2>1. Source &amp; Sample &mdash; {def.label}</h2>
            <dl className="kv">
              <dt>SAP source</dt><dd className="mono">{def.sapTable}</dd>
              <dt>Oracle target</dt><dd>{def.oracleTarget}</dd>
              <dt>FBDI template</dt><dd className="mono">{def.fbdiTemplate}</dd>
              <dt>Fields mapped</dt><dd>{def.fields.length}</dd>
            </dl>
            <p className="hint">Download a ready-to-use sample extract for this object, then move to Extract / Load.</p>
            <div className="row-actions">
              <button className="btn secondary" onClick={handleDownloadSample}>Download Sample File</button>
              <button className="btn" onClick={() => goStep('load')}>Next: Extract / Load &rarr;</button>
            </div>
          </div>
        )}

        {stepKey === 'load' && (
          <div>
            <h2>2. Extract / Load &mdash; {def.label}</h2>
            <p className="hint">Upload a CSV extract or load the built-in sample. Loaded rows are staged below.</p>
            <div className="row-actions">
              <input ref={fileRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={handleUpload} />
              <button className="btn secondary" onClick={() => fileRef.current?.click()}>Upload CSV</button>
              <button className="btn secondary" onClick={handleDownloadSample}>Download Sample File</button>
              <button className="btn" onClick={() => loadSample(def.id)}>Load Sample Data</button>
              {st.loaded && <button className="btn danger small" onClick={() => resetObject(def.id)}>Reset</button>}
            </div>
            {uploadName && <p className="hint">Uploaded: {uploadName}</p>}
            {st.loaded ? (
              <>
                <p style={{ marginTop: 12 }}><strong>{st.sourceRows.length}</strong> records staged.</p>
                <PreviewTable headers={headers} rows={st.sourceRows} />
                <div className="row-actions" style={{ marginTop: 12 }}>
                  <button className="btn" onClick={() => goStep('validate')}>Next: Validate &rarr;</button>
                </div>
              </>
            ) : (
              <p className="hint" style={{ marginTop: 12 }}>No data loaded yet.</p>
            )}
          </div>
        )}

        {stepKey === 'validate' && (
          <div>
            <h2>3. Validate &mdash; {def.label} <StatusBadge status={validationBadge()} /></h2>
            <p className="hint">Runs data-quality rules (required fields, numeric &amp; date formats) against staged records.</p>
            <div className="row-actions">
              <button className="btn" disabled={!st.loaded} onClick={() => validate(def.id)}>Run Validation</button>
              {!st.loaded && <span className="hint">Load data first.</span>}
            </div>
            {st.validation.ran && (
              <div style={{ marginTop: 12 }}>
                <p>
                  Valid: <strong>{st.validation.validCount}</strong> &nbsp;|&nbsp;
                  Errors: <strong>{st.validation.errorCount}</strong>
                </p>
                {st.validation.errorCount > 0 && (
                  <ul className="error-list">
                    {st.validation.errors.map((e, i) => (
                      <li key={i}>Row {e.row}, {e.field} &rarr; {e.oracle}: {e.message}</li>
                    ))}
                  </ul>
                )}
                <PreviewTable headers={headers} rows={st.sourceRows} errorRows={new Set(st.validation.errors.map((e) => e.row))} />
                <div className="row-actions" style={{ marginTop: 12 }}>
                  <button className="btn" onClick={() => goStep('transform')}>Next: Transform &amp; Preview &rarr;</button>
                </div>
              </div>
            )}
          </div>
        )}

        {stepKey === 'transform' && (
          <div>
            <h2>4. Transform &amp; Preview &mdash; {def.label}</h2>
            <p className="hint">Applies the SAP &rarr; Oracle Fusion field mapping &amp; transforms below.</p>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr><th>SAP field</th><th>Type</th><th>Oracle Fusion field</th><th>Transform</th><th>Required</th></tr>
                </thead>
                <tbody>
                  {def.fields.map((f) => (
                    <tr key={f.sap}>
                      <td className="mono">{f.sap}</td><td>{f.sapType}</td>
                      <td className="mono">{f.oracle}</td><td>{f.transform}</td>
                      <td>{f.required ? 'Yes' : 'No'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row-actions" style={{ marginTop: 12 }}>
              <button className="btn" disabled={!st.loaded} onClick={() => transform(def.id)}>Transform &amp; Preview</button>
              {!st.loaded && <span className="hint">Load data first.</span>}
            </div>
            {st.transform.ran && (
              <>
                <p style={{ marginTop: 12 }}>Transformed output preview ({st.transform.output.length} records):</p>
                <PreviewTable headers={oracleHeaders} rows={st.transform.output} />
                <div className="row-actions" style={{ marginTop: 12 }}>
                  <button className="btn" onClick={() => goStep('migrate')}>Next: Migrate &rarr;</button>
                </div>
              </>
            )}
          </div>
        )}

        {stepKey === 'migrate' && (
          <div>
            <h2>5. Migrate to Oracle Fusion &mdash; {def.label} <StatusBadge status={st.migration.status} /></h2>
            <p className="hint">Loads valid transformed records into Oracle Fusion via {def.fbdiTemplate}.</p>
            <div className="row-actions">
              <button
                className="btn"
                disabled={!st.loaded || st.migration.status === STATUS.IN_PROGRESS}
                onClick={() => migrate(def.id)}
              >
                {st.migration.status === STATUS.IN_PROGRESS ? 'Migrating…' : 'Migrate'}
              </button>
              {!st.loaded && <span className="hint">Load data first.</span>}
            </div>
            {st.migration.status !== STATUS.NOT_STARTED && (
              <div style={{ marginTop: 14 }}>
                <div className="progress"><span style={{ width: `${st.migration.progress}%` }} /></div>
                <p className="hint" style={{ marginTop: 6 }}>{st.migration.progress}%</p>
                {st.migration.summary && <p><strong>{st.migration.summary}</strong></p>}
                {st.migration.progress === 100 && (
                  <div className="row-actions">
                    <button className="btn" onClick={() => goStep('output')}>Next: Reconcile &amp; Output &rarr;</button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {stepKey === 'output' && (
          <div>
            <h2>6. Reconcile &amp; Output &mdash; {def.label}</h2>
            <dl className="kv">
              <dt>Source records</dt><dd>{st.sourceRows.length}</dd>
              <dt>Migrated</dt><dd>{st.migration.migratedCount}</dd>
              <dt>Rejected</dt><dd>{st.migration.failedCount}</dd>
              <dt>Status</dt><dd><StatusBadge status={st.migration.status} /></dd>
            </dl>
            {st.migration.summary && <p><strong>{st.migration.summary}</strong></p>}
            <div className="row-actions" style={{ marginTop: 12 }}>
              <button className="btn secondary" disabled={!st.loaded} onClick={handleDownloadOutput}>Download Migrated Output</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Reusable preview table (first 20 rows) with optional error-row highlighting.
function PreviewTable({ headers, rows, errorRows }) {
  if (!rows || rows.length === 0) return <p className="hint">No rows to display.</p>
  const shown = rows.slice(0, 20)
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>#</th>
            {headers.map((h) => <th key={h} className="mono">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i} className={errorRows && errorRows.has(i + 1) ? 'err-row' : ''}>
              <td>{i + 1}</td>
              {headers.map((h) => <td key={h}>{String(r[h] ?? '')}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length && <p className="hint">Showing {shown.length} of {rows.length} rows.</p>}
    </div>
  )
}
