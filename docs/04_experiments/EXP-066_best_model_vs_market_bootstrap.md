# EXP-066 — Bootstrap aktualnego najlepszego modelu vs rynek

> [!abstract]
> Sprawdzono, czy aktualny produkcyjny hybrid `Hybrid-Thesis-Market/a0.35-t0.80` statystycznie bije rynek bukmacherski na wspólnej próbce EXP-060/061. Model poprawia LogLoss względem rynku opening/mid, ale względem rynku close poprawa jest mała i nieistotna na poziomie 5%. Miesięczny block bootstrap nie potwierdza istotności dla żadnego wariantu, głównie przez tylko 3 bloki miesięczne w próbce.

## Metadata

- **Experiment ID:** EXP-066
- **Date:** 2026-07-30
- **Tags:** `#exp039` `#hybrid` `#market-comparison` `#bootstrap` `#significance-test`
- **Model:** `Hybrid-Thesis-Market/a0.35-t0.80`
- **Formula:** `p_hybrid = 0.35 * temperature(EXP039, T=0.80) + 0.65 * market_probability`
- **Input:** `reports/exp039_db_market_backtest_v2/exp039_market_common.csv`
- **Output:** `reports/exp066_best_model_vs_market_bootstrap/summary.json`
- **Script:** `betting_app/scripts/bootstrap_best_model_vs_market.py`
- **Seed:** 42

## Method

Dla każdego meczu na wspólnej próbce liczony jest LogLoss rynku i hybrydy. Różnica:

```text
ΔLogLoss = market_loss - hybrid_loss
```

Dodatnie `ΔLogLoss` oznacza, że hybryda ma niższy LogLoss niż rynek na tym samym meczu.

Testy:

1. paired t-test na per-match różnicach,
2. sign test liczby meczów, w których hybryda ma niższy loss,
3. sign-flip permutation test,
4. zwykły bootstrap po meczach,
5. miesięczny block bootstrap po blokach `YYYY-MM`.

## Results

| Market timing | N | Months | Market LL | Hybrid LL | Δ market-hybrid | Match bootstrap 95% CI | Perm. p | Block bootstrap 95% CI | Block p | Wniosek |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| open | 408 | 3 | 0.5830 | 0.5622 | +0.0208 | [0.0050, 0.0368] | 0.0058 | [-0.0085, 0.0299] | 0.1545 | model lepszy per-match, niepotwierdzone blokowo |
| mid | 408 | 3 | 0.5768 | 0.5592 | +0.0176 | [0.0020, 0.0334] | 0.0148 | [-0.0100, 0.0249] | 0.1529 | model lepszy per-match, niepotwierdzone blokowo |
| close | 408 | 3 | 0.5659 | 0.5546 | +0.0113 | [-0.0034, 0.0264] | 0.0731 | [-0.0158, 0.0232] | 0.2551 | brak istotności 5% |

Dodatkowo dla close market:

- paired t-test p-value one-sided: `0.0706`,
- sign test: `262` wygrane hybrydy vs `146` przegranych, p-value `4.99e-09`,
- ale LogLoss bootstrap/permutation nie przekracza progu 5%.

## Interpretation

- Hybryda `a0.35-t0.80` poprawia średni LogLoss względem rynku na tej próbce.
- Najważniejszym benchmarkiem jest **market close**. Tam poprawa wynosi tylko `+0.0113` LogLoss i nie jest istotna statystycznie przy α=0.05.
- Wynik jest zachęcający, ale nie wystarcza do tezy „model jest udowodnialnie lepszy od rynku close”. Bezpieczna interpretacja: model jest na poziomie rynku close i może dodawać mały sygnał, ale wymaga większej próbki czasowej.
- Block bootstrap jest najbardziej konserwatywny, bo chroni przed zależnością czasową; obecna próbka obejmuje tylko 3 miesiące, więc przedziały są szerokie.

## Conclusion

> [!check]
> `Hybrid-Thesis-Market/a0.35-t0.80` jest najlepszym praktycznym wariantem hybrydowym i poprawia LogLoss względem rynku open/mid.

> [!bug]
> Dla rynku close brak istotności statystycznej na poziomie 5%; nie należy raportować, że model jednoznacznie bije closing market.

Next steps:

1. Kontynuować zbieranie próbek po wdrożeniu `a0.35`, żeby zwiększyć liczbę miesięcznych bloków.
2. Raportować model jako „competitive with close market / small positive edge not yet statistically confirmed”.
3. Powtórzyć EXP-066 po uzyskaniu co najmniej 6–12 miesięcznych bloków albo po backfillu większej historycznej próbki closing odds.
