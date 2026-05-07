import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import roc_auc_score, log_loss
import os

def main():
    print("Running 10_final_comparison_kelly.py...")
    os.makedirs("docs/assets", exist_ok=True)
    
    # 1. Load Data
    df_meta = pd.read_csv("data/golgg_stacking_results.csv")
    df_odds = pd.read_csv("data/odds.csv")
    
    df_meta['golgg_match_id'] = df_meta['golgg_match_id'].astype(str)
    df_odds['golgg_match_id'] = df_odds['golgg_match_id'].astype(str)
    
    # Calculate Market Prob
    df_odds['prob_market'] = 1 / df_odds['avg_odds_home'] / ((1/df_odds['avg_odds_home']) + (1/df_odds['avg_odds_away']))
    
    # Max odds for simulation
    df_odds['max_open_t1'] = df_odds[['odds1_sts_open', 'odds1_superbet_open', 'odds1_betclic_open', 'odds1_efortuna_open', 'odds1_lv_bet_open', 'odds1_betfan_open']].max(axis=1)
    df_odds['max_open_t2'] = df_odds[['odds2_sts_open', 'odds2_superbet_open', 'odds2_betclic_open', 'odds2_efortuna_open', 'odds2_lv_bet_open', 'odds2_betfan_open']].max(axis=1)

    # Merge
    df = pd.merge(df_meta[['golgg_match_id', 'metamodel_lgbm_prob', 'y_true', 'date']], 
                  df_odds[['golgg_match_id', 'prob_market', 'max_open_t1', 'max_open_t2']], 
                  on='golgg_match_id')
    
    df = df.dropna()
    df['date'] = pd.to_datetime(df['date'])
    
    # Filter since 2024 (Modern Era)
    df = df[df['date'] >= '2024-01-01'].sort_values('date').reset_index(drop=True)
    
    # Hybrid Model (Alpha = 0.5168 from Chapter 7)
    alpha = 0.5168
    df['prob_hybrid'] = alpha * df['metamodel_lgbm_prob'] + (1 - alpha) * df['prob_market']
    
    # 2. Simulation Parameters
    start_bankroll = 100.0
    tax = 0.12
    net_mult = 0.88
    stake_cap = 100.0
    min_stake = 2.0
    slippage = 0.01
    f_kelly = 0.25 # Quarter Kelly
    
    models = [
        ("Metamodel", "metamodel_lgbm_prob", "blue"),
        ("Market Avg", "prob_market", "red"),
        ("Hybrid Model", "prob_hybrid", "green")
    ]
    
    plt.figure(figsize=(12, 8))
    np.random.seed(42)
    
    # Final Stats
    results = []
    for name, prob_col, color in models:
        # Re-run simulation to get final metrics
        curr_br = start_bankroll
        br_history = [start_bankroll]
        turnover = 0
        count = 0
        wins = 0
        
        for _, row in df.iterrows():
            p = row[prob_col]
            ev1 = (row['max_open_t1'] * net_mult * p) - 1
            ev2 = (row['max_open_t2'] * net_mult * (1-p)) - 1
            
            if ev1 > 0.05:
                o_raw, prob, is_win = row['max_open_t1'], p, (1 if row['y_true'] == 1 else 0)
            elif ev2 > 0.05:
                o_raw, prob, is_win = row['max_open_t2'], 1-p, (1 if row['y_true'] == 0 else 0)
            else:
                br_history.append(curr_br)
                continue
            
            noise = np.random.normal(0, 0.02)
            o_exec = o_raw * (1 - slippage) + noise
            o_exec = max(o_exec, 1.01)
            
            b_net = (o_raw * net_mult) - 1
            k_stake_pct = (b_net * prob - (1 - prob)) / b_net
            k_stake_pct = max(0, k_stake_pct) * f_kelly
            
            stake = min(curr_br * k_stake_pct, stake_cap)
            if stake < min_stake or curr_br < stake:
                br_history.append(curr_br)
                continue
                
            count += 1
            turnover += stake
            if is_win:
                wins += 1
            profit = (stake * o_exec * net_mult) - stake if is_win else -stake
            curr_br += profit
            br_history.append(curr_br)
            
        br_history = np.array(br_history)
        peak = np.maximum.accumulate(br_history)
        drawdown = (peak - br_history) / (peak + 1e-9)
        max_dd = np.max(drawdown) * 100
        
        results.append({
            "Model": name,
            "Final Bankroll": curr_br,
            "Yield": (curr_br - start_bankroll) / turnover if turnover > 0 else 0,
            "Max DD (%)": max_dd,
            "Bets": count,
            "Win Rate (%)": (wins / count * 100) if count > 0 else 0
        })
        
        # Plot with dates
        # We need to align br_history with dates. 
        # br_history has start_bankroll + one entry per row in df
        plt.plot(df['date'], br_history[1:], label=name, color=color, linewidth=2 if name=="Hybrid Model" else 1.5)

    res_df = pd.DataFrame(results)
    print("\n=== FINAL KELLY COMPARISON (f=0.25) ===")
    print(res_df.to_string(index=False))
    res_df.to_csv("docs/assets/final_kelly_comparison_metrics.csv", index=False)

    plt.title("Final Comparison: Bankroll Growth (2024-2026, Kelly f=0.25)")
    plt.ylabel("Bankroll ($)")
    plt.xlabel("Date")
    plt.axhline(100, color='black', linestyle='--')
    plt.legend()
    plt.grid(alpha=0.3)
    plt.savefig("docs/assets/final_bankroll_comparison_kelly.png")
    
    print("\n10_final_comparison_kelly.py completed.")

if __name__ == "__main__":
    main()
