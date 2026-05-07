import pandas as pd
import numpy as np
from sklearn.metrics import roc_auc_score, log_loss, brier_score_loss, accuracy_score
from datetime import datetime
import os

def calculate_ece(y_true, y_prob, n_bins=10):
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    bin_lowers = bin_boundaries[:-1]
    bin_uppers = bin_boundaries[1:]
    ece = 0
    for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
        in_bin = (y_prob > bin_lower) & (y_prob <= bin_upper)
        prop_in_bin = np.mean(in_bin)
        if prop_in_bin > 0:
            accuracy_in_bin = np.mean(y_true[in_bin])
            avg_confidence_in_bin = np.mean(y_prob[in_bin])
            ece += np.abs(avg_confidence_in_bin - accuracy_in_bin) * prop_in_bin
    return ece

def main():
    print("Running 08_evaluate_models.py...")
    os.makedirs("docs/assets", exist_ok=True)
    
    df = pd.read_csv("data/golgg_final_hybrid_results.csv")
    df['date'] = pd.to_datetime(df['date'])
    df_modern = df[df['date'] >= datetime(2024, 1, 1)].copy()
    
    models = {
        'Hybrid Model': 'final_hybrid_prob',
        'Metamodel (Stage 2)': 'metamodel_lgbm_calibrated',
        'Rating Ensemble (Stage 1)': 's1_prob',
        'Player Glicko2 (Baseline)': 'player_gl',
        'Market Avg (Open)': 'prob_avg_open'
    }
    
    perf_results = []
    for name, col in models.items():
        temp_df = df_modern.dropna(subset=['y_true', col])
        y_true = temp_df['y_true']
        y_prob = temp_df[col]
        y_pred = (y_prob > 0.5).astype(int)
        
        perf_results.append({
            'Model': name,
            'AUC': roc_auc_score(y_true, y_prob),
            'LogLoss': log_loss(y_true, y_prob),
            'Brier': brier_score_loss(y_true, y_prob),
            'ECE': calculate_ece(y_true, y_prob),
            'ACC (%)': accuracy_score(y_true, y_pred) * 100
        })
    
    res_df = pd.DataFrame(perf_results)
    print("\n=== Comprehensive Performance Metrics (2024-Present) ===")
    print(res_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    
    res_df.to_csv("docs/assets/comprehensive_metrics_2024.csv", index=False)
    print("\nSaved docs/assets/comprehensive_metrics_2024.csv")
    print("08_evaluate_models.py completed successfully.")

if __name__ == "__main__":
    main()
