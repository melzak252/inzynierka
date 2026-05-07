import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
import os

def kelly_criterion(p, b):
    if b <= 0 or p <= 0:
        return 0
    q = 1 - p
    return (b * p - q) / b

def simulate_roi(df, model_col, initial_bankroll=1000, kelly_fraction=0.25, kelly_cap=100, tax_rate=0.12, slippage=0.02, ev_threshold=0.05, ban_prob=0.1):
    bookies = ["betclic", "betfan", "efortuna", "lv_bet", "sts", "superbet"]
    np.random.seed(42)
    
    bankroll = initial_bankroll
    total_staked = 0
    total_profit = 0
    total_bets = 0
    
    history = []
    dates = []
    
    for _, match in df.iterrows():
        max_o1 = 0
        max_o2 = 0
        
        for b in bookies:
            if np.random.rand() < ban_prob:
                continue
            o1 = match.get(f'odds1_{b}_open')
            o2 = match.get(f'odds2_{b}_open')
            if pd.notnull(o1) and pd.notnull(o2) and o1 > 1 and o2 > 1:
                if o1 > max_o1: max_o1 = o1
                if o2 > max_o2: max_o2 = o2
        
        if max_o1 <= 1 or max_o2 <= 1:
            continue
            
        max_o1 *= (1 - slippage)
        max_o2 *= (1 - slippage)
        
        p1 = match.get(model_col)
        if pd.isnull(p1): continue
        p2 = 1 - p1
        
        win1 = 1 if match['y_true'] == 1 else 0
        win2 = 1 if match['y_true'] == 0 else 0
        
        eff_o1 = max_o1 * (1 - tax_rate)
        ev1 = (p1 * eff_o1) - 1
        eff_o2 = max_o2 * (1 - tax_rate)
        ev2 = (p2 * eff_o2) - 1
        
        profit = 0
        stake = 0
        bet_placed = False
        
        if ev1 > ev2 and ev1 > ev_threshold and max_o1 > 1.2:
            f = kelly_criterion(p1, eff_o1 - 1) * kelly_fraction
            stake = min(bankroll * f, kelly_cap)
            if stake >= 2.0:
                profit = stake * (eff_o1 - 1) if win1 else -stake
                bet_placed = True
        elif ev2 > ev1 and ev2 > ev_threshold and max_o2 > 1.2:
            f = kelly_criterion(p2, eff_o2 - 1) * kelly_fraction
            stake = min(bankroll * f, kelly_cap)
            if stake >= 2.0:
                profit = stake * (eff_o2 - 1) if win2 else -stake
                bet_placed = True
        
        if bet_placed:
            bankroll += profit
            total_staked += stake
            total_profit += profit
            total_bets += 1
            history.append(bankroll)
            dates.append(match['date'])
            
    yield_pct = (total_profit / total_staked * 100) if total_staked > 0 else 0
    roi_pct = (total_profit / initial_bankroll * 100)
    
    history_arr = np.array(history)
    if len(history_arr) > 0:
        running_max = np.maximum.accumulate(history_arr)
        drawdowns = (running_max - history_arr) / running_max * 100
        max_drawdown = np.max(drawdowns)
    else:
        max_drawdown = 0
        
    return {
        'Total Bets': total_bets,
        'Yield (%)': yield_pct,
        'ROI (%)': roi_pct,
        'Max Drawdown (%)': max_drawdown,
        'Final Bankroll': bankroll,
        'Total Profit': total_profit,
        'history': history,
        'dates': dates
    }

def main():
    print("Running 09_simulate_roi.py...")
    os.makedirs("docs/assets", exist_ok=True)
    
    df = pd.read_csv("data/golgg_final_hybrid_results.csv")
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values("date").reset_index(drop=True)
    
    df_2020 = df[df['date'] >= datetime(2020, 1, 1)].copy()
    df_2024 = df[df['date'] >= datetime(2024, 1, 1)].copy()
    
    models = {
        'Player Glicko-2': 'player_gl',
        'Metamodel (Stage 2)': 'metamodel_lgbm_calibrated',
        'Hybrid Model': 'final_hybrid_prob'
    }
    
    # 1. Long-Term Performance (2020+)
    plt.figure(figsize=(12, 6))
    results_2020 = []
    for name, col in models.items():
        res = simulate_roi(df_2020, col)
        results_2020.append({'Model': name, **{k: v for k, v in res.items() if k not in ['history', 'dates']}})
        plt.plot(res['dates'], res['history'], label=f"{name} (Yield: {res['Yield (%)']:.1f}%)")
        
    plt.title("Bankroll Growth (2020-Present): $100 Stake Cap")
    plt.xlabel("Date")
    plt.ylabel("Bankroll ($)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("docs/assets/roi_model_comparison.png")
    
    print("\n=== Long-Term Performance (2020-Present) ===")
    print(pd.DataFrame(results_2020).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    
    # 2. Modern Era (2024+)
    plt.figure(figsize=(12, 6))
    results_2024 = []
    for name, col in models.items():
        res = simulate_roi(df_2024, col)
        results_2024.append({'Model': name, **{k: v for k, v in res.items() if k not in ['history', 'dates']}})
        plt.plot(res['dates'], res['history'], label=f"{name} (Yield: {res['Yield (%)']:.1f}%)")
        
    plt.title("Bankroll Growth (2024-Present): $100 Stake Cap")
    plt.xlabel("Date")
    plt.ylabel("Bankroll ($)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("docs/assets/roi_2024_present.png")
    
    print("\n=== Modern Era Performance (2024-Present) ===")
    print(pd.DataFrame(results_2024).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    
    # 3. Scalability ($500 Cap)
    plt.figure(figsize=(12, 6))
    results_500 = []
    for name, col in models.items():
        res = simulate_roi(df_2024, col, kelly_cap=500)
        results_500.append({'Model': name, **{k: v for k, v in res.items() if k not in ['history', 'dates']}})
        plt.plot(res['dates'], res['history'], label=f"{name} (Yield: {res['Yield (%)']:.1f}%)")
        
    plt.title("Bankroll Growth (2024-Present): $500 Stake Cap")
    plt.xlabel("Date")
    plt.ylabel("Bankroll ($)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("docs/assets/roi_2024_present_cap500.png")
    
    print("\n=== Scalability ($500 Cap, 2024-Present) ===")
    print(pd.DataFrame(results_500).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    
    # 4. Kelly Sensitivity
    kelly_fractions = [0.10, 0.25, 0.50, 0.75, 1.00]
    kelly_results = []
    for kf in kelly_fractions:
        res = simulate_roi(df_2024, 'final_hybrid_prob', kelly_fraction=kf)
        kelly_results.append({'Kelly Fraction': kf, **{k: v for k, v in res.items() if k not in ['history', 'dates']}})
        
    print("\n=== Kelly Sensitivity (Hybrid Model, 2024-Present) ===")
    print(pd.DataFrame(kelly_results).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    
    # 5. Bookmaker Analysis
    bookies = ["betclic", "betfan", "efortuna", "lv_bet", "sts", "superbet"]
    bookie_results = []
    for b in bookies:
        # Simulate with only one bookie available
        temp_df = df_2024.copy()
        for other_b in bookies:
            if other_b != b:
                temp_df[f'odds1_{other_b}_open'] = np.nan
                temp_df[f'odds2_{other_b}_open'] = np.nan
        res = simulate_roi(temp_df, 'final_hybrid_prob', ban_prob=0.0) # No random bans for this test
        bookie_results.append({'Bookmaker': b.upper(), **{k: v for k, v in res.items() if k not in ['history', 'dates']}})
        
    print("\n=== Bookmaker Analysis (Hybrid Model, 2024-Present) ===")
    print(pd.DataFrame(bookie_results).sort_values('Total Profit', ascending=False).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    
    # 6. Tier Analysis
    tier1_keywords = [
        "LEC", "LCS", "LTA", "LCK", "LPL", 
        "European Championship", "Championship Series", "Champions Korea", "Pro League",
        "Mid-Season Invitational", "Mid Season Invitational", "First Stand", 
        "World Championship", "Mistrzostwa Świata"
    ]
    def is_tier1(tournament):
        t = str(tournament)
        if "Pro League" in t and "Oceanic" not in t and "Continental" not in t:
            return True
        return any(kw in t for kw in tier1_keywords)
        
    df_2024['is_tier1'] = df_2024['tournament'].apply(is_tier1)
    tier_results = []
    for tier_name, mask in [("Tier 1", df_2024['is_tier1']), ("Regional/ERL", ~df_2024['is_tier1'])]:
        res = simulate_roi(df_2024[mask].copy(), 'final_hybrid_prob')
        tier_results.append({'Tier': tier_name, **{k: v for k, v in res.items() if k not in ['history', 'dates']}})
        
    print("\n=== Tier Analysis (Hybrid Model, 2024-Present) ===")
    print(pd.DataFrame(tier_results).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    
    # 7. BoN Analysis
    bon_results = []
    for bon in [1, 3, 5]:
        res = simulate_roi(df_2024[df_2024['BoN'] == bon].copy(), 'final_hybrid_prob')
        bon_results.append({'Format': f'Best-of-{bon}', **{k: v for k, v in res.items() if k not in ['history', 'dates']}})
        
    print("\n=== BoN Analysis (Hybrid Model, 2024-Present) ===")
    print(pd.DataFrame(bon_results).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    
    print("\n09_simulate_roi.py completed successfully.")

if __name__ == "__main__":
    main()
