import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import MatchList from './pages/MatchList'
import MatchDetail from './pages/MatchDetail'
import MatchResults from './pages/MatchResults'
import SystemPage from './pages/SystemPage'
import HorizonAnalysis from './pages/HorizonAnalysis'
import ManualMapping from './pages/ManualMapping'
import './App.css'

function Nav() {
  const location = useLocation()

  const links = [
    { to: '/', label: 'Mecze' },
    { to: '/results', label: 'Wyniki' },
    { to: '/mapping', label: 'Mapowanie' },
    { to: '/horizon', label: 'Horizon' },
    { to: '/system', label: 'System' },
  ]

  return (
    <nav className="main-nav">
      <div className="nav-brand">
        <Link to="/">EnsembleLegends</Link>
      </div>
      <div className="nav-links">
        {links.map((link) => (
          <Link
            key={link.to}
            to={link.to}
            className={location.pathname === link.to ? 'active' : ''}
          >
            {link.label}
          </Link>
        ))}
      </div>
    </nav>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Nav />
      <main className="app-main">
        <Routes>
          <Route path="/" element={<MatchList />} />
          <Route path="/matches/:id" element={<MatchDetail />} />
          <Route path="/results" element={<MatchResults />} />
          <Route path="/mapping" element={<ManualMapping />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="/horizon" element={<HorizonAnalysis />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}

export default App
