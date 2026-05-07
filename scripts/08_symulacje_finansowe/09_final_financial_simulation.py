import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import roc_auc_score, log_loss
import os

def main():
    print("Running 09_final_financial_simulation.py (Adaptive Hybrid)...")
    os.makedirs("docs/assets", exist_ok=True)
    
    # 1. Load Data
    df_meta = pd.read_csv("data/golgg_stacking_results.csv")
    df_odds = pd.read_csv("data/odds.csv")
    
    df_meta['golgg_match_id'] = df_meta['golgg_match_id'].astype(str)
    df_odds['golgg_match_id'] = df_odds['golgg_match_id'].astype(str)
    
    # Calculate Market Prob
    df_odds['prob_market'] = 1 / df_odds['avg_odds_home'] / ((1/df_odds['avg_odds_home']) + (1/df_odds['avg_odds_away']))
    
    # Max odds for EV
    df_odds['max_open_t1'] = df_odds[['odds1_sts_open', 'odds1_superbet_open', 'odds1_betclic_open', 'odds1_efortuna_open', 'odds1_lv_bet_open', 'odds1_betfan_open']].max(axis=1)
    df_odds['max_open_t2'] = df_odds[['odds2_sts_open', 'odds2_superbet_open', 'odds2_betclic_open', 'odds2_efortuna_open', 'odds2_lv_bet_open', 'odds2_betfan_open']].max(axis=1)
    
    # Merge
    df = pd.merge(df_meta[['golgg_match_id', 'metamodel_lgbm_prob', 'y_true', 'date']], 
                  df_odds[['golgg_match_id', 'prob_market', 'max_open_t1', 'max_open_t2', 'tournament']], 
                  on='golgg_match_id')
    
    df = df.dropna()
    df['date'] = pd.to_datetime(df['date'])
    df = df[df['date'] >= '2024-01-01'].sort_values('date').reset_index(drop=True)

    # 2. Adaptive Hybrid Model (Online Learning)
    history_br = [100.0]
    curr_br = 100.0
    
    # Simulation Parameters
    tax = 0.12
    net_mult = 0.88
    stake_cap = 100.0
    min_stake = 2.0
    slippage = 0.01
    
    # Adaptive Alpha Parameters
    err_meta_rolling = 0.25
    err_market_rolling = 0.25
    learning_rate = 0.05
    
    alpha_history = []
    breakdown_data = []
    
    # For Tier/BoN analysis
    tier1_keywords = ["LEC", "LCS", "LTA", "LCK", "LPL", "European Championship", "Championship Series", "Champions Korea", "Pro League", "Mid-Season Invitational", "World Championship"]
    def is_tier1_local(tournament):
        t = str(tournament)
        if "Pro League" in t and "Oceanic" not in t and "Continental" not in t: return True
        return any(kw in t for kw in tier1_keywords)

    df_odds_full = pd.read_csv("data/odds.csv")
    df_odds_full['golgg_match_id'] = df_odds_full['golgg_match_id'].astype(str)
    if 'BoN' not in df_odds_full.columns:
        df_odds_full['BoN'] = df_odds_full['t1_score'] + df_odds_full['t2_score']
        df_odds_full['BoN'] = df_odds_full['BoN'].apply(lambda x: 1 if x <= 1 else (3 if x <= 3 else 5))

    df = pd.merge(df, df_odds_full[['golgg_match_id', 'BoN']], on='golgg_match_id')
    df['is_tier1'] = df['tournament'].apply(is_tier1_local)

    np.random.seed(42)
    
    for _, row in df.iterrows():
        # Calculate current Alpha
        alpha_raw = err_market_rolling / (err_meta_rolling + err_market_rolling + 1e-9)
        # We scale alpha to a safe range [0.0, 0.5] to keep market as anchor
        alpha = np.clip(alpha_raw * 0.3, 0.0, 0.5) 
        alpha_history.append(alpha)
        
        p = alpha * row['metamodel_lgbm_prob'] + (1 - alpha) * row['prob_market']
        
        # Betting Logic
        ev1 = (row['max_open_t1'] * net_mult * p) - 1
        ev2 = (row['max_open_t2'] * net_mult * (1-p)) - 1
        
        selected_bet = None
        if ev1 > 0.05:
            selected_bet = {'odds': row['max_open_t1'], 'prob': p, 'is_win': (1 if row['y_true'] == 1 else 0)}
        elif ev2 > 0.05:
            selected_bet = {'odds': row['max_open_t2'], 'prob': 1-p, 'is_win': (1 if row['y_true'] == 0 else 0)}
            
        if selected_bet:
            noise = np.random.normal(0, 0.02)
            o_exec = selected_bet['odds'] * (1 - slippage) + noise
            o_exec = max(o_exec, 1.01)
            
            b_net = (selected_bet['odds'] * net_mult) - 1
            # Quarter Kelly (f=0.25)
            k_stake_pct = max(0, (b_net * selected_bet['prob'] - (1 - selected_bet['prob'])) / b_net) * 0.25
            
            stake = min(curr_br * k_stake_pct, stake_cap)
            if stake >= min_stake:
                profit = (stake * o_exec * net_mult) - stake if selected_bet['is_win'] else -stake
                curr_br += profit
                breakdown_data.append({
                    "Tier": "Tier 1" if row['is_tier1'] else "ERL/Regional", 
                    "BoN": f"Bo{int(row['BoN'])}", 
                    "Profit": profit
                })
        
        history_br.append(curr_br)
        
        # Update Rolling Errors
        e_meta = (row['metamodel_lgbm_prob'] - row['y_true'])**2
        e_market = (row['prob_market'] - row['y_true'])**2
        err_meta_rolling = (1 - learning_rate) * err_meta_rolling + learning_rate * e_meta
        err_market_rolling = (1 - learning_rate) * err_market_rolling + learning_rate * e_market

    # Final Stats
    history_br = np.array(history_br)
    peak = np.maximum.accumulate(history_br)
    drawdown = (peak - history_br) / (peak + 1e-9)
    max_dd = np.max(drawdown) * 100
    
    print(f"\n=== FINAL ADAPTIVE HYBRID RESULTS (2024-2026) ===")
    print(f"Final Bankroll: {curr_br:.2f}$")
    print(f"Max Drawdown:   {max_dd:.2f}%")
    print(f"Min Bankroll:   {np.min(history_br):.2f}$")
    
    # Plotting ROI
    plt.figure(figsize=(12, 6))
    plt.plot(df['date'], history_br[1:], label="Adaptive Hybrid (Kelly f=0.25)", color='green', linewidth=2)
    plt.title("Final Financial Simulation: Adaptive Hybrid Model (2024-2026)")
    plt.ylabel("Bankroll ($)")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.savefig("docs/assets/roi_simulation_2024.png")

    # Plotting Alpha Evolution
    plt.figure(figsize=(12, 4))
    plt.plot(df['date'], alpha_history, color='purple')
    plt.title("Evolution of Adaptive Alpha (Trust Score)")
    plt.ylabel("Alpha Weight")
    plt.grid(alpha=0.3)
    plt.savefig("docs/assets/final_alpha_evolution.png")

    # Breakdown Plots
    br_df = pd.DataFrame(breakdown_data)
    if not br_df.empty:
        plt.figure(figsize=(10, 6))
        br_df.groupby('Tier')['Profit'].sum().plot(kind='bar', color=['blue', 'orange'])
        plt.title("Total Profit by League Tier (Adaptive Hybrid)")
        plt.ylabel("Profit ($)")
        plt.xticks(rotation=0)
        plt.savefig("docs/assets/final_profit_by_tier.png")
        
        plt.figure(figsize=(10, 6))
        br_df.groupby('BoN')['Profit'].sum().plot(kind='bar', color='green')
        plt.title("Total Profit by Match Format (Adaptive Hybrid)")
        plt.ylabel("Profit ($)")
        plt.xticks(rotation=0)
        plt.savefig("docs/assets/final_profit_by_bon.png")
    
    print("\n09_final_financial_simulation.py completed.")

if __name__ == "__main__":
    main()
