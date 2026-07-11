import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import MigrationPage from './pages/MigrationPage.jsx'
import ArchitecturePage from './pages/ArchitecturePage.jsx'

// App shell: Bank of America header (logo + theme) shown on every page, plus routing
// between the Migration workspace and the interactive Architecture page.
export default function App() {
  return (
    <div>
      <header className="app-header">
        <img className="logo" src="/assets/bank-of-america-logo.svg" alt="Bank of America" />
        <nav>
          <NavLink to="/migration" className={({ isActive }) => (isActive ? 'active' : '')}>
            Migration
          </NavLink>
          <NavLink to="/architecture" className={({ isActive }) => (isActive ? 'active' : '')}>
            Architecture
          </NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/migration" replace />} />
          <Route path="/migration" element={<MigrationPage />} />
          <Route path="/migration/:step" element={<MigrationPage />} />
          <Route path="/architecture" element={<ArchitecturePage />} />
          <Route path="*" element={<Navigate to="/migration" replace />} />
        </Routes>
      </main>
    </div>
  )
}
