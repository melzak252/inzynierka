import { useEffect, useState } from 'react';

import { getApiHealth } from './api/health';
import './styles.css';

type ApiStatus = 'checking' | 'online' | 'offline';

function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking');

  useEffect(() => {
    let isMounted = true;

    getApiHealth()
      .then(() => {
        if (isMounted) {
          setApiStatus('online');
        }
      })
      .catch(() => {
        if (isMounted) {
          setApiStatus('offline');
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <main className="app-shell">
      <section className="hero-card">
        <p className="eyebrow">EnsembleLegends</p>
        <h1>Porównywanie drużyn i predykcja meczów LoL</h1>
        <p className="lead">
          Startowa aplikacja React + FastAPI przygotowana pod wyszukiwarkę drużyn,
          profil matchupów i endpoint predykcyjny modelu hybrydowego.
        </p>

        <div className="status-grid" aria-label="Status usług">
          <div className="status-card">
            <span className={`status-dot status-dot--${apiStatus}`} />
            <div>
              <strong>FastAPI</strong>
              <p>{apiStatus === 'checking' ? 'Sprawdzanie...' : apiStatus}</p>
            </div>
          </div>
          <div className="status-card">
            <span className="status-dot status-dot--planned" />
            <div>
              <strong>PostgreSQL</strong>
              <p>podłączony przez backend</p>
            </div>
          </div>
        </div>

        <div className="next-steps">
          <h2>Następne moduły</h2>
          <ul>
            <li>import danych GOL.GG do PostgreSQL,</li>
            <li>endpoint wyszukiwania drużyn,</li>
            <li>endpoint porównania dwóch drużyn,</li>
            <li>warstwa inferencji modelu predykcyjnego.</li>
          </ul>
        </div>
      </section>
    </main>
  );
}

export default App;
