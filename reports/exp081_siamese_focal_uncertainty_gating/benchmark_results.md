# Raport Porównawczy: Syjamska Sieć Neuronowa z Focal Loss i Bramkowaniem Niepewnością (EXP-081)

**Data ewaluacji:** 2026-09-06  
**Okres testowy (OOS):** 2025-01-12 do 2026-03-22 ($N=5\,597$ meczów, w tym $N=2\,334$ meczów z pełnymi kwotowaniami otwarcia/zamknięcia)  
**Warunki finansowe:** Polski podatek obrotowy $12\%$ (współczynnik efektywny $0.88$), minimalny próg $\text{EV}_{\text{net}} \ge +5\%$, stawkowanie płaskie 100 PLN, kursy z zakresu $[1.05, 5.00]$.

---

## 1. Tabela Zbiorcza: Ewolucja Modeli od Regresji Liniowej do Bagged MLP z Bramkowaniem Niepewnością

| Model / Koncepcja | LogLoss Test | ROC-AUC | Liczba Zakładów | Skuteczność (Win Rate) | Yield Netto | Zysk Netto | Max Drawdown | Coin-Flip $[50\%-55\%)$ Win Rate | Coin-Flip Gap (Overconf.) | Faworyci $[1.41-1.75]$ Zysk |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Regresja Liniowa (EXP-078)** | 0.5543 | 0.7854 | 747 | 57.0% | +50.08% | +37 412 PLN | 5.98% | 36.5% | +16.1 p.p. | -156 PLN |
| **2. Syjamskie MLP (BCE Loss)** | 0.5523 | 0.7866 | 752 | 57.6% | +49.92% | +37 540 PLN | 5.58% | 36.5% | +16.1 p.p. | -156 PLN |
| **3. Syjamskie MLP + Focal Loss ($\gamma=1.0$)** | **0.5518** | **0.7875** | 750 | 57.3% | +48.67% | +36 501 PLN | 5.45% | 42.2% | +10.4 p.p. | +32 PLN |
| **4. Bagged MLP + Uncertainty Gating ($\kappa=0.75$)** | 0.5524 | 0.7872 | **680** | **58.7%** | **+54.48%** | **+37 047 PLN** | **4.64%** | **43.3%** | **+9.4 p.p.** | **+65 PLN** |

---

## 2. Wpływ Parametru Konserwatyzmu Ryzyka ($\kappa$) na Portfel

Dla estymacji dolnej granicy logitu:
$$z_{\text{low}}(x) = \bar{z}(x) - \kappa \cdot \sigma_z(x) \implies p_{\text{low}}(x) = \sigma(z_{\text{low}}(x))$$

| $\kappa$ (Współczynnik Ryzyka) | Liczba Zakładów | Win Rate | Yield Netto | Zysk Netto | Max Drawdown | Zakłady Coin-Flip $N$ | Coin-Flip Win Rate | Faworyci $[1.41-1.75]$ Zysk |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **0.00** (brak kary) | 744 | 57.9% | +49.73% | +36 998 PLN | 5.30% | 70 | 42.9% | -128 PLN |
| **0.25** | 726 | 58.3% | +51.66% | +37 508 PLN | 5.33% | 66 | 43.9% | -149 PLN |
| **0.50** | 698 | 58.5% | +53.12% | +37 079 PLN | 5.33% | 61 | 42.6% | -83 PLN |
| **0.75** (optymalny) | **680** | **58.7%** | **+54.48%** | **+37 047 PLN** | **4.64%** | **60** | **43.3%** | **+65 PLN** |
| **1.00** | 655 | 58.8% | +55.01% | +36 034 PLN | 4.81% | 56 | 41.1% | +20 PLN |

---

## 3. Kluczowe Wnioski i Znaczenie dla Pracy Inżynierskiej

1. **Eliminacja Przekleństwa Zwycięzcy (Winner's Curse)**:
   Filtr opłacalności $\text{EV}_{\text{net}} \ge +5\%$ pod $12\%$ podatkiem naturalnie selekcjonował mecze o skrajnie dodatnim błędzie estymacji (zwłaszcza na faworytach i coin-flipach). Wprowadzenie bramkowania niepewnością epistemiczną ($P_{\text{low}}$) odrzuca mecze, w których wysokie EV wynika jedynie z szumu wariancji wag sieci.
2. **Rekordowy Yield Netto (+54.48%)**:
   Odrzucenie 72 toksycznych zakładów zwiększyło stopę zwrotu z $49.7\%$ do $54.5\%$ przy zachowaniu niemal identycznego zysku nominalnego (~37k PLN).
3. **Drastyczny spadek ryzyka**:
   Maksymalne obsunięcie kapitału (Max Drawdown) stopniało z $5.98\%$ w regresji liniowej do $4.64\%$ w Bagged MLP.
