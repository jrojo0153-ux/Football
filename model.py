"""
model.py - Núcleo Matemático Institucional
Implementa: Distribución de Poisson, Expected Value (+EV), Kelly Fraccional.
Aprende de history_master.csv para ajustar pesos.
"""

import numpy as np
from scipy.stats import poisson
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import pandas as pd
import pickle
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    KELLY_FRACTION, MIN_EV_THRESHOLD, CONFIDENCE_THRESHOLD,
    POISSON_WEIGHT_HOME, POISSON_WEIGHT_AWAY, MODEL_DIR, HISTORY_FILE
)


class PoissonGoalModel:
    """Modelo de Poisson para predicción de goles."""

    def __init__(self):
        self.league_averages = {}  # Promedios por liga aprendidos del historial

    def load_league_averages(self):
        """Carga promedios históricos del archivo de historial."""
        if os.path.exists(HISTORY_FILE):
            df = pd.read_csv(HISTORY_FILE)
            if not df.empty and "league" in df.columns:
                for league in df["league"].unique():
                    league_data = df[df["league"] == league]
                    self.league_averages[league] = {
                        "avg_home_goals": league_data["home_goals"].mean(),
                        "avg_away_goals": league_data["away_goals"].mean(),
                        "avg_total_goals": (league_data["home_goals"] + league_data["away_goals"]).mean()
                    }

    def predict_goals(self, home_attack: float, home_defense: float,
                      away_attack: float, away_defense: float,
                      league_avg_goals: float = 2.65) -> dict:
        """
        Predice goles esperados usando Poisson.
        
        Args:
            home_attack: Promedio de goles a favor del local
            home_defense: Promedio de goles en contra del local
            away_attack: Promedio de goles a favor del visitante
            away_defense: Promedio de goles en contra del visitante
            league_avg_goals: Promedio de goles por partido en la liga
        
        Returns:
            Dict con lambda_home, lambda_away y matriz de probabilidades
        """
        league_avg_home = league_avg_goals * 0.53  # ~53% goles son del local
        league_avg_away = league_avg_goals * 0.47

        # Fuerza de ataque y defensa relativa
        home_attack_strength = home_attack / max(league_avg_home, 0.5)
        away_attack_strength = away_attack / max(league_avg_away, 0.5)
        home_defense_strength = home_defense / max(league_avg_away, 0.5)
        away_defense_strength = away_defense / max(league_avg_home, 0.5)

        # Lambda (goles esperados)
        lambda_home = home_attack_strength * away_defense_strength * league_avg_home * POISSON_WEIGHT_HOME
        lambda_away = away_attack_strength * home_defense_strength * league_avg_away * POISSON_WEIGHT_AWAY

        # Limitar lambdas a valores razonables
        lambda_home = max(0.3, min(lambda_home, 4.5))
        lambda_away = max(0.2, min(lambda_away, 4.0))

        # Matriz de probabilidades (0-5 goles cada equipo)
        max_goals = 6
        prob_matrix = np.zeros((max_goals, max_goals))
        for i in range(max_goals):
            for j in range(max_goals):
                prob_matrix[i][j] = poisson.pmf(i, lambda_home) * poisson.pmf(j, lambda_away)

        return {
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "prob_matrix": prob_matrix
        }

    def get_match_probabilities(self, prob_matrix: np.ndarray) -> dict:
        """
        Calcula probabilidades 1X2 y Over/Under desde la matriz de Poisson.
        """
        max_goals = prob_matrix.shape[0]

        p_home = 0
        p_draw = 0
        p_away = 0
        p_over_25 = 0
        p_under_25 = 0
        p_btts_yes = 0

        for i in range(max_goals):
            for j in range(max_goals):
                p = prob_matrix[i][j]
                if i > j:
                    p_home += p
                elif i == j:
                    p_draw += p
                else:
                    p_away += p

                if i + j > 2:
                    p_over_25 += p
                else:
                    p_under_25 += p

                if i > 0 and j > 0:
                    p_btts_yes += p

        return {
            "home_win": p_home,
            "draw": p_draw,
            "away_win": p_away,
            "over_2.5": p_over_25,
            "under_2.5": p_under_25,
            "btts_yes": p_btts_yes,
            "btts_no": 1 - p_btts_yes
        }


class EVCalculator:
    """Calcula Expected Value y Kelly Criterion."""

    @staticmethod
    def calculate_ev(model_prob: float, decimal_odds: float) -> float:
        """
        Calcula Expected Value.
        EV = (Probabilidad * (Cuota - 1)) - (1 - Probabilidad)
        
        Returns:
            EV como porcentaje (ej: 0.15 = +15% EV)
        """
        ev = (model_prob * (decimal_odds - 1)) - (1 - model_prob)
        return ev

    @staticmethod
    def calculate_kelly(model_prob: float, decimal_odds: float,
                        fraction: float = KELLY_FRACTION) -> float:
        """
        Calcula Kelly Criterion fraccional.
        Kelly = (bp - q) / b
        Donde: b = odds-1, p = prob ganar, q = prob perder
        
        Returns:
            Porcentaje del bankroll a apostar (0-1)
        """
        b = decimal_odds - 1
        p = model_prob
        q = 1 - p

        if b <= 0:
            return 0

        kelly = (b * p - q) / b
        kelly_fractional = kelly * fraction

        # No apostar si Kelly es negativo o muy bajo
        return max(0, min(kelly_fractional, 0.10))  # Cap en 10% del bankroll

    @staticmethod
    def calculate_brier_score(predictions: list, outcomes: list) -> float:
        """
        Calcula Brier Score para evaluar precisión del modelo.
        Menor = mejor. 0 = perfecto, 0.25 = random.
        """
        if not predictions or not outcomes:
            return 0.25
        n = len(predictions)
        return sum((p - o) ** 2 for p, o in zip(predictions, outcomes)) / n


class FormAdjuster:
    """Ajusta probabilidades basándose en forma reciente y historial."""

    def __init__(self):
        self.historical_weights = {}
        self._load_weights()

    def _load_weights(self):
        """Carga pesos aprendidos del historial."""
        weights_file = os.path.join(MODEL_DIR, "learned_weights.pkl")
        if os.path.exists(weights_file):
            with open(weights_file, "rb") as f:
                self.historical_weights = pickle.load(f)

    def save_weights(self):
        """Guarda pesos actualizados."""
        os.makedirs(MODEL_DIR, exist_ok=True)
        weights_file = os.path.join(MODEL_DIR, "learned_weights.pkl")
        with open(weights_file, "wb") as f:
            pickle.dump(self.historical_weights, f)

    def adjust_probability(self, base_prob: float, team_features: dict,
                           h2h_data: list = None) -> float:
        """
        Ajusta la probabilidad base con factores de forma y H2H.
        
        Args:
            base_prob: Probabilidad del modelo Poisson
            team_features: Features del equipo (forma, goles, etc.)
            h2h_data: Historial de enfrentamientos directos
        """
        adjustment = 0.0

        # Factor forma reciente (últimos 5 partidos)
        form_points = team_features.get("form_points", 7.5)  # 7.5 = promedio
        form_factor = (form_points - 7.5) / 15  # Normalizado [-0.5, 0.5]
        adjustment += form_factor * 0.08  # Max ±4% ajuste por forma

        # Factor H2H
        if h2h_data and len(h2h_data) >= 3:
            team_id = team_features.get("team_id")
            h2h_wins = sum(1 for m in h2h_data
                          if (m["teams"]["home"]["id"] == team_id and
                              m["teams"]["home"]["winner"]) or
                          (m["teams"]["away"]["id"] == team_id and
                           m["teams"]["away"]["winner"]))
            h2h_rate = h2h_wins / len(h2h_data)
            h2h_factor = (h2h_rate - 0.33) * 0.06  # Max ±4% ajuste por H2H
            adjustment += h2h_factor

        # Aplicar ajuste con límites
        adjusted = base_prob + adjustment
        return max(0.05, min(adjusted, 0.95))


def evaluate_pick(model_prob: float, odds: float) -> dict:
    """
    Evalúa si un pick tiene valor.
    
    Returns:
        Dict con EV, Kelly, y si es recomendable.
    """
    ev = EVCalculator.calculate_ev(model_prob, odds)
    kelly = EVCalculator.calculate_kelly(model_prob, odds)

    is_value = (ev >= MIN_EV_THRESHOLD and
                model_prob >= CONFIDENCE_THRESHOLD and
                kelly > 0)

    return {
        "ev": ev,
        "ev_pct": f"+{ev*100:.2f}%" if ev > 0 else f"{ev*100:.2f}%",
        "kelly": kelly,
        "kelly_pct": f"{kelly*100:.2f}%",
        "is_value_bet": is_value,
        "confidence": model_prob,
        "odds": odds,
        "rating": "⭐⭐⭐" if ev > 0.15 else "⭐⭐" if ev > 0.08 else "⭐"
    }


if __name__ == "__main__":
    # Ejemplo de uso
    poisson_model = PoissonGoalModel()
    
    # Simular: Cruz Azul (local) vs Chivas (visitante)
    result = poisson_model.predict_goals(
        home_attack=1.8,   # Cruz Azul marca 1.8 goles/partido en casa
        home_defense=0.7,  # Cruz Azul recibe 0.7 goles/partido en casa
        away_attack=1.4,   # Chivas marca 1.4 goles/partido fuera
        away_defense=1.2,  # Chivas recibe 1.2 goles/partido fuera
        league_avg_goals=2.5  # Promedio Liga MX
    )
    
    probs = poisson_model.get_match_probabilities(result["prob_matrix"])
    print(f"Lambda Local: {result['lambda_home']:.2f}")
    print(f"Lambda Visitante: {result['lambda_away']:.2f}")
    print(f"Probabilidades: Home {probs['home_win']:.2%} | Draw {probs['draw']:.2%} | Away {probs['away_win']:.2%}")
    print(f"Over 2.5: {probs['over_2.5']:.2%} | Under 2.5: {probs['under_2.5']:.2%}")
    
    # Evaluar pick
    pick = evaluate_pick(probs["home_win"], 1.85)
    print(f"\nPick: Local gana @ 1.85")
    print(f"  EV: {pick['ev_pct']} | Kelly: {pick['kelly_pct']} | Valor: {pick['is_value_bet']}")
