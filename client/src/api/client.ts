import type { MatchBoardResponse, MatchDetailResponse } from '../types';

const API_BASE = '/api';

export async function fetchMatches(
  minBooks: number = 1,
  daysAhead: number = 14
): Promise<MatchBoardResponse> {
  const params = new URLSearchParams({
    min_books: minBooks.toString(),
    days_ahead: daysAhead.toString(),
  });
  
  const response = await fetch(`${API_BASE}/matches?${params}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch matches: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchMatchDetail(matchId: number): Promise<MatchDetailResponse> {
  const response = await fetch(`${API_BASE}/matches/${matchId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch match ${matchId}: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchHealth(): Promise<{ status: string; version: string }> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error(`Failed to fetch health: ${response.statusText}`);
  }
  return response.json();
}
