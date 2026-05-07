import sys
import os
sys.path.append(os.getcwd())
import json
import numpy as np
from tqdm import tqdm
from datetime import date
import pandas as pd

from src.ratings.manager import RatingManager

def add_to_y_predicts(y_predicts, predictions, bon, date, match_id):
    predictions["BoN"] = bon
    predictions["date"] = date
    predictions["golgg_match_id"] = match_id

    current_len = 0
    if y_predicts:
        current_len = len(next(iter(y_predicts.values())))

    for key, value in predictions.items():
        if key not in y_predicts:
            y_predicts[key] = [None] * current_len
        y_predicts[key].append(value)

    for key in y_predicts:
        if key not in predictions:
            y_predicts[key].append(None)

def main():
    print("Running 03_generate_ratings.py...")
    print("Loading golgg_matches.json...")
    with open("data/golgg_matches.json", "r", encoding="utf-8") as f:
        matches = json.load(f)

    matches = [match for match in matches if not match["draw"]]
    print(f"Matches without draws: {len(matches)}")

    # Initialize RatingManager with parameters selected in
    # scripts/05b_optimize_trueskill_openskill.py.
    optimal_params = {
        "ts": {"mu": 25.0, "sigma": 8.333, "beta": 4.16, "tau": 0.25},
        "os": {"mu": 25.0, "sigma": 3.5},
    }
    manager = RatingManager(optimal_params)
    
    y_predicts = {}
    y_trues = []

    print("Processing matches and calculating ratings...")
    for match in tqdm(matches, desc="Processing matches"):
        t1 = match["tid_1"]
        t2 = match["tid_2"]
        match_date = date.fromisoformat(match["date"])
        players_1 = match["players_1"]
        players_2 = match["players_2"]
        scores = []

        match_info = manager.update_before_match(
            t1, t2, players_1, players_2, match_date
        )
        predictions = manager.predict_match(t1, t2, players_1, players_2)

        # Add contextual features
        predictions["days_since_last_1"] = match_info["days_since_last_1"]
        predictions["days_since_last_2"] = match_info["days_since_last_2"]
        predictions["days_diff"] = (
            match_info["days_since_last_1"] - match_info["days_since_last_2"]
        )

        add_to_y_predicts(y_predicts, predictions, match["BoN"], match_date, match["match_id"])
        y_trues.append(int(match["t1_win"]))

        for game in match["games"]:
            score_1 = int(game["t1_win"])
            score_2 = 1 - score_1
            if game["t1_id"] != match["tid_1"]:
                score_1, score_2 = score_2, score_1

            scores.append(score_1)
            manager.update_after_game(t1, t2, players_1, players_2, score_1, score_2)

        manager.update_after_match(t1, t2, players_1, players_2, scores)

    print("Saving results to golgg_y_predicts.csv...")
    df = pd.DataFrame(y_predicts)
    df["y_true"] = y_trues
    df.to_csv("data/golgg_y_predicts.csv", index=False)
    print("03_generate_ratings.py completed successfully.")

if __name__ == "__main__":
    main()
