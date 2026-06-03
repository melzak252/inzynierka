import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import MatchList from './pages/MatchList'
import MatchDetail from './pages/MatchDetail'
import SystemStatus from './pages/SystemStatus'
import SchedulerPanel from './pages/SchedulerPanel'
import TimingAnalysis from './pages/TimingAnalysis'
import HorizonAnalysis from './pages/HorizonAnalysis'
import './App.css'

function Nav() {
  const location = useLocation()

  const links = [
    { to: '/', label: 'Mecze' },
    { to: '/timing', label: 'Timing' },
    { to: '/horizon', label: 'Horizon' },
    { to: '/system', label: 'System' },
    { to: '/scheduler', label: 'Scheduler' },
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
          <Route path="/system" element={<SystemStatus />} />
          <Route path="/scheduler" element={<SchedulerPanel />} />
          <Route path="/timing" element={<TimingAnalysis />} />
          <Route path="/horizon" element={<HorizonAnalysis />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}

export default App
