from typing import List, Dict, Any
from datetime import date
from .elo import EloRating
from .glicko import GlickoRating
from .trueskill_rating import TrueSkillRating
from .plackett_luce import PlackettLuceRating
from .thurstone import ThurstoneRating

from .openskill_rating import OpenSkillRating

class RatingManager:
    def __init__(self, params: Dict[str, Any] = {}):
        params = params or {}
        self.systems = {
            "elo": EloRating(**params.get("elo", {})),
            "gl": GlickoRating(**params.get("gl", {})),
            "ts": TrueSkillRating(**params.get("ts", {"tau": 0.166})),
            "os": OpenSkillRating(**params.get("os", {"sigma": 5.0})),
            "pl": PlackettLuceRating(**params.get("pl", {"beta": 18.75, "tau": 0.0833})),
            "tm": ThurstoneRating(**params.get("tm", {"beta": 18.75, "tau": 0.0833}))
        }
        self.last_match_date = {} # team_id -> date

    def update_before_match(self, t1: str, t2: str, players_1: List[str], players_2: List[str], match_date: date) -> Dict[str, Any]:
        # Only Glicko needs time decay before match
        self.systems["gl"].update_rd_before_match(t1, t2, players_1, players_2, match_date)
        
        # Calculate days since last match
        days_1 = (match_date - self.last_match_date[t1]).days if t1 in self.last_match_date else 30
        days_2 = (match_date - self.last_match_date[t2]).days if t2 in self.last_match_date else 30
        
        # Update last match date
        self.last_match_date[t1] = match_date
        self.last_match_date[t2] = match_date
        
        return {"days_since_last_1": days_1, "days_since_last_2": days_2}

    def predict_match(self, t1: str, t2: str, players_1: List[str], players_2: List[str]) -> Dict[str, float]:
        predictions = {}
        for name, system in self.systems.items():
            # Win probabilities
            predictions[f"team_{name}"] = system.predict_team_win_prob(t1, t2)
            predictions[f"player_{name}"] = system.predict_player_win_prob(players_1, players_2)
            
            # Raw ratings for teams
            r1 = system.get_team_rating(t1)
            r2 = system.get_team_rating(t2)
            
            if name == "elo":
                predictions[f"team_{name}_r1"] = r1
                predictions[f"team_{name}_r2"] = r2
            elif name == "gl":
                predictions[f"team_{name}_r1"] = r1.rating
                predictions[f"team_{name}_rd1"] = r1.rd
                predictions[f"team_{name}_r2"] = r2.rating
                predictions[f"team_{name}_rd2"] = r2.rd
            else: # ts, os, pl, tm
                predictions[f"team_{name}_mu1"] = r1.mu
                predictions[f"team_{name}_sigma1"] = r1.sigma
                predictions[f"team_{name}_mu2"] = r2.mu
                predictions[f"team_{name}_sigma2"] = r2.sigma
                
            # Raw ratings for players
            p1_ratings = [system.get_player_rating(p) for p in players_1]
            p2_ratings = [system.get_player_rating(p) for p in players_2]
            
            if name == "elo":
                p1_vals = p1_ratings
                p2_vals = p2_ratings
                predictions[f"player_{name}_min1"] = min(p1_vals) if p1_vals else 1500.0
                predictions[f"player_{name}_min2"] = min(p2_vals) if p2_vals else 1500.0
            elif name == "gl":
                p1_vals = [p.rating for p in p1_ratings]
                p2_vals = [p.rating for p in p2_ratings]
                predictions[f"player_{name}_max1"] = max(p1_vals) if p1_vals else 1500.0
                predictions[f"player_{name}_max2"] = max(p2_vals) if p2_vals else 1500.0
                
            # Add volatility/deviation features
            if name == "gl":
                predictions[f"player_{name}_rd_avg1"] = sum(p.rd for p in p1_ratings) / len(p1_ratings) if p1_ratings else 350.0
                predictions[f"player_{name}_rd_avg2"] = sum(p.rd for p in p2_ratings) / len(p2_ratings) if p2_ratings else 350.0
            elif name in ["ts", "os", "pl", "tm"]:
                predictions[f"player_{name}_sigma_avg1"] = sum(p.sigma for p in p1_ratings) / len(p1_ratings) if p1_ratings else 8.333
                predictions[f"player_{name}_sigma_avg2"] = sum(p.sigma for p in p2_ratings) / len(p2_ratings) if p2_ratings else 8.333
                
        return predictions


    def update_after_game(self, t1: str, t2: str, players_1: List[str], players_2: List[str], score_1: int, score_2: int) -> None:
        # Update all systems except Glicko which is updated per match
        for name, system in self.systems.items():
            if name != "gl":
                system.update_team(t1, t2, score_1, score_2)
                system.update_player(players_1, players_2, score_1, score_2)

    def update_after_match(self, t1: str, t2: str, players_1: List[str], players_2: List[str], scores: List[int]) -> None:
        # Glicko takes a list of scores for the match
        # To fit the interface, we'll just pass the sum of scores or iterate.
        # The original code passed the list of scores to update_player.
        # Let's adapt Glicko to handle the list of scores directly or iterate.
        
        # In our refactored Glicko, we implemented it per game. 
        # So we should actually update Glicko per game or modify it.
        # For simplicity and to match original logic, let's iterate through scores.
        for score_1 in scores:
            score_2 = 1 - score_1
            self.systems["gl"].update_team(t1, t2, score_1, score_2)
            self.systems["gl"].update_player(players_1, players_2, score_1, score_2)
