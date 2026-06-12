import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { UnmappedMatchItem, GolggMatchCandidate } from '../types';
import './ManualMapping.css';

const API_BASE = '/api';

const ManualMapping: React.FC = () => {
  const [unmappedMatches, setUnmappedMatches] = useState<UnmappedMatchItem[]>([]);
  const [selectedMatch, setSelectedMatch] = useState<UnmappedMatchItem | null>(null);
  const [candidates, setCandidates] = useState<GolggMatchCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [mappingStatus, setMappingStatus] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('expired');

  useEffect(() => {
    fetchUnmapped();
  }, [statusFilter]);

  const fetchUnmapped = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/matches/unmapped?status=${statusFilter}`);
      setUnmappedMatches(res.data.matches);
    } catch (err) {
      console.error('Failed to fetch unmapped matches', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectMatch = async (match: UnmappedMatchItem) => {
    setSelectedMatch(match);
    setCandidates([]);
    setMappingStatus(null);
    try {
      const res = await axios.get(`${API_BASE}/matches/${match.canonical_match_id}/mapping-candidates`);
      setCandidates(res.data.candidates);
    } catch (err) {
      console.error('Failed to fetch candidates', err);
    }
  };

  const handleMap = async (golggMatchId: number) => {
    if (!selectedMatch) return;
    try {
      await axios.post(`${API_BASE}/matches/map`, {
        canonical_match_id: selectedMatch.canonical_match_id,
        golgg_match_id: golggMatchId
      });
      setMappingStatus('Success!');
      // Refresh list and clear selection
      fetchUnmapped();
      setSelectedMatch(null);
      setCandidates([]);
    } catch (err) {
      setMappingStatus('Failed to map match');
      console.error(err);
    }
  };

  return (
    <div className="manual-mapping-page">
      <h1>Ręczne Mapowanie GOL.GG</h1>
      
      <div className="mapping-container">
        <div className="unmapped-list-section">
          <div className="section-header">
            <h2>Niezmapowane mecze</h2>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="expired">Expired</option>
              <option value="upcoming">Upcoming</option>
              <option value="finished">Finished</option>
            </select>
          </div>
          
          {loading ? <p>Ładowanie...</p> : (
            <div className="scroll-list">
              {unmappedMatches.map(m => (
                <div 
                  key={m.canonical_match_id} 
                  className={`match-item ${selectedMatch?.canonical_match_id === m.canonical_match_id ? 'selected' : ''}`}
                  onClick={() => handleSelectMatch(m)}
                >
                  <div className="match-time">{m.start_time_normalized?.split('T')[0]}</div>
                  <div className="match-teams">{m.team_a_name} vs {m.team_b_name}</div>
                  <div className="match-league">{m.league}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="candidates-section">
          {selectedMatch ? (
            <>
              <h2>Kandydaci GOL.GG dla:</h2>
              <div className="selected-match-info">
                <strong>{selectedMatch.team_a_name} vs {selectedMatch.team_b_name}</strong>
                <p>{selectedMatch.start_time_normalized}</p>
              </div>

              {mappingStatus && <div className="status-msg">{mappingStatus}</div>}

              <div className="candidates-list">
                {candidates.length === 0 ? <p>Brak kandydatów w oknie +/- 3 dni.</p> : (
                  candidates.map(c => (
                    <div key={c.match_id} className="candidate-item">
                      <div className="candidate-info">
                        <div className="candidate-date">{c.date}</div>
                        <div className="candidate-teams">{c.team1_name} vs {c.team2_name}</div>
                        <div className="candidate-result">
                          {c.team1_win !== null ? (c.team1_win ? 'W1' : 'W2') : 'No result'}
                        </div>
                      </div>
                      <button onClick={() => handleMap(c.match_id)}>Mapuj</button>
                    </div>
                  ))
                )}
              </div>
            </>
          ) : (
            <div className="empty-state">Wybierz mecz z listy po lewej, aby zobaczyć kandydatów.</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ManualMapping;
