import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import MatchList from './pages/MatchList'
import MatchDetail from './pages/MatchDetail'
import MatchResults from './pages/MatchResults'
import SystemPage from './pages/SystemPage'
import ModelAnalysis from './pages/ModelAnalysis'
import ManualMapping from './pages/ManualMapping'
import ChampionEmbeddings from './pages/ChampionEmbeddings'
import FinancialAnalysis from './pages/FinancialAnalysis'
import './App.css'

function Nav() {
  const location = useLocation()

  const links = [
    { to: '/', label: 'Mecze' },
    { to: '/results', label: 'Backtest' },
    { to: '/financial', label: 'Finanse' },
    { to: '/horizon', label: 'Analiza modelu' },
    { to: '/embeddings/champions', label: 'Embeddingi' },
    { to: '/mapping', label: 'Mapowania' },
    { to: '/system', label: 'Monitoring' },
  ]

  return (
    <nav className="main-nav">
      <div className="nav-brand">
        <Link to="/">
          <span className="brand-mark">EL</span>
          <span className="brand-copy">
            <strong>EnsembleLegends</strong>
            <small>betting intelligence</small>
          </span>
        </Link>
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
          <Route path="/financial" element={<FinancialAnalysis />} />
          <Route path="/mapping" element={<ManualMapping />} />
          <Route path="/embeddings/champions" element={<ChampionEmbeddings />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="/horizon" element={<ModelAnalysis />} />
          <Route path="/bootstrap" element={<ModelAnalysis />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}

export default App
