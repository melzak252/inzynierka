import sys
from pathlib import Path
import pandas as pd
import numpy as np
from tqdm import tqdm
from collections import deque
import json

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from betting_app.core.db import get_session
from sqlalchemy import text

def fetch_all_games_from_db():
    """Fetch all GOL.GG games with necessary stats from Postgres."""
    query = """
    SELECT 
        g.game_id,
        g.match_id,
        g.date,
        g.team1_id,
        g.team2_id,
        g.team1_win,
        g.team2_win,
        g.team1_side,
        g.team2_side,
        g.game_duration,
        g.team1_stats_json,
        g.team2_stats_json,
        m.best_of,
        m.tournament_name
    FROM golgg_games g
    JOIN golgg_matches m ON g.match_id = m.match_id
    ORDER BY g.date ASC, g.game_id ASC
    """
    print("Fetching games from database...")
    with get_session() as session:
        df = pd.read_sql(text(query), session.connection())
    
    # Convert date to datetime
    df['date'] = pd.to_datetime(df['date'])
    return df

def extract_team_stats(stats_json_str):
    if not stats_json_str:
        return {}
    try:
        return json.loads(stats_json_str)
    except:
        return {}

def build_transformer_dataset(df, window_size=10):
    """
    Build a dataset where each row is a match, and features are sequences of last N games for both teams.
    """
    team_history = {} # team_id -> deque of game features
    
    # Features to extract per game
    # [win, side, duration, kills, deaths, gold, towers, dragons, nashors]
    
    dataset = []
    
    # Group by match_id to process matches as units (important for leakage safety)
    # But games are already ordered by date.
    
    # We need to be careful: for a match, we want the history *before* the first game of that match.
    matches = df.groupby('match_id', sort=False)
    
    for match_id, match_games in tqdm(matches, desc="Processing matches"):
        first_game = match_games.iloc[0]
        t1_id = first_game['team1_id']
        t2_id = first_game['team2_id']
        
        # Get history for both teams BEFORE this match
        t1_seq = list(team_history.get(t1_id, []))
        t2_seq = list(team_history.get(t2_id, []))
        
        # Pad sequences if shorter than window_size
        def pad_sequence(seq, size):
            if len(seq) >= size:
                return seq[-size:]
            # Zero padding (or we could use a special mask value)
            padding = [[0.0] * 9] * (size - len(seq))
            return padding + seq

        t1_padded = pad_sequence(t1_seq, window_size)
        t2_padded = pad_sequence(t2_seq, window_size)
        
        # Target: who won the match? (using the match result, or just the first game for simplicity in this prototype)
        # In GOL.GG matches, team1_win is 1 if team1 won the WHOLE match.
        # Wait, golgg_matches has team1_win/team2_win for the match.
        # Let's use the first game's match-level info if available, or just the game result.
        
        # For now, let's just store the sequences and the match result.
        dataset.append({
            'match_id': match_id,
            't1_id': t1_id,
            't2_id': t2_id,
            't1_seq': t1_padded,
            't2_seq': t2_padded,
            'y': 1 if first_game['team1_win'] == 1 else 0, # This might be game-level win, need to check
            'date': first_game['date']
        })
        
        # Update history with games from THIS match
        for _, game in match_games.iterrows():
            # Team 1 stats
            s1 = extract_team_stats(game['team1_stats_json'])
            s2 = extract_team_stats(game['team2_stats_json'])
            
            f1 = [
                float(game['team1_win'] or 0),
                1.0 if game['team1_side'] == 'Blue' else 0.0,
                float(game['game_duration'] or 0) / 1800.0, # Normalize roughly to 30 mins
                float(s1.get('kills') or 0) / 20.0,
                float(s2.get('kills') or 0) / 20.0, # T1 deaths = T2 kills
                float(s1.get('gold') or 0) / 60000.0,
                float(s1.get('towers') or 0) / 11.0,
                float(s1.get('dragons') or 0) / 4.0,
                float(s1.get('nashors') or 0) / 2.0,
            ]
            if t1_id not in team_history: team_history[t1_id] = deque(maxlen=window_size)
            team_history[t1_id].append(f1)
            
            # Team 2 stats
            f2 = [
                float(game['team2_win'] or 0),
                1.0 if game['team2_side'] == 'Blue' else 0.0,
                float(game['game_duration'] or 0) / 1800.0,
                float(s2.get('kills') or 0) / 20.0,
                float(s1.get('kills') or 0) / 20.0, # T2 deaths = T1 kills
                float(s2.get('gold') or 0) / 60000.0,
                float(s2.get('towers') or 0) / 11.0,
                float(s2.get('dragons') or 0) / 4.0,
                float(s2.get('nashors') or 0) / 2.0,
            ]
            if t2_id not in team_history: team_history[t2_id] = deque(maxlen=window_size)
            team_history[t2_id].append(f2)

    return dataset

if __name__ == "__main__":
    df = fetch_all_games_from_db()
    print(f"Total games: {len(df)}")
    
    dataset = build_transformer_dataset(df, window_size=15)
    print(f"Dataset size: {len(dataset)}")
    
    # Save to file
    output_path = PROJECT_ROOT / "data" / "transformer_team_sequences_v1.json"
    # We use a custom encoder for datetime or just convert to string
    def default_serializer(obj):
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    with open(output_path, 'w') as f:
        json.dump(dataset, f, default=default_serializer)
    
    print(f"Saved dataset to {output_path}")
