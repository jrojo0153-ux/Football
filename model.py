import numpy as np
import pandas as pd
import pickle
import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    KELLY_FRACTION, MIN_EV_THRESHOLD, CONFIDENCE_THRESHOLD,
    POISSON_WEIGHT_HOME, POISSON_WEIGHT_AWAY, MODEL_DIR, HISTORY_FILE
)

# Configuración de registro estructurado para Confiabilidad (SRE)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class PoissonGoalModel:
    """Modelo de Poisson altamente optimizado para predicción de goles sin dependencias pesadas."""

    def __init__(self):
        self.league_averages = {}

    def load_league_averages(self):
        """Carga promedios históricos controlando excepciones y estructuras vacías."""
        if os.path.exists(HISTORY_FILE):
            try:
                df = pd.read_csv(HISTORY_FILE)
                required_cols = {"league", "home_goals", "away_goals"}
                if not df.empty and required_cols.issubset(df.columns):
                    for league in df["league"].unique():
                        league_data = df[df["league"] == league]
                        if not league_data.empty:
                            avg_home = league_data["home_goals"].mean()
                            avg_away = league_data["away_goals"].mean()
                            self.league_averages[league] = {
                                "avg_home_goals": avg_home,
                                "avg_away_goals": avg_away,
                                "avg_total_goals": avg_home + avg_away
                            }
            except Exception as e:
                logger.error("Error al cargar promedios de liga desde %s: %s", HISTORY_FILE, e, exc_info=True)

    def predict_goals(self, home_attack: float, home_defense: float,
                      away_attack: float, away_defense: float,
                      league_avg_goals: float = 2.65) -> dict:
        """
        Predice goles esperados usando Poisson vectorizado (sin scipy).
        """
        league_avg_home = max(league_avg_goals * 0.53, 0.1)
        league_avg_away = max(league_avg_goals * 0.47, 0.1)

        home_attack_strength = home_attack / max(league_avg_home, 0.5)
        away_attack_strength = away_attack / max(league_avg_away, 0.5)
        home_defense_strength = home_defense / max(league_avg_away, 0.5)
        away_defense_strength = away_defense / max(league_avg_home, 0.5)

        lambda_home = home_attack_strength * away_defense_strength * league_avg_home * POISSON_WEIGHT_HOME
        lambda_away = away_attack_strength * home_defense_strength * league_avg_away * POISSON_WEIGHT_AWAY

        lambda_home = max(0.3, min(lambda_home, 4.5))
        lambda_away = max(0.2, min(lambda_away, 4.0))

        # Vectorización ultra-eficiente de Poisson (0 a 5 goles)
        fact = np.array([1.0, 1.0, 2.0, 6.0, 24.0, 120.0])
        k = np.arange(6)
        prob_home = np.exp(-lambda_home) * (lambda_home ** k) / fact
        prob_away = np.exp(-lambda_away) * (lambda_away ** k) / fact
        prob_matrix = np.outer(prob_home, prob_away)

        return {
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "prob_matrix": prob_matrix
        }

    def get_match_probabilities(self, prob_matrix: np.ndarray) -> dict:
        """
        Calcula probabilidades 1X2 y Over/Under mediante operaciones matriciales nativas.
        """
        p_home = float(np.sum(np.tril(prob_matrix, -1)))
        p_draw = float(np.sum(np.diag(prob_matrix)))
        p_away = float(np.sum(np.triu(prob_matrix, 1)))

        grid = np.fromfunction(lambda i, j: i + j, prob_matrix.shape, dtype=int)
        p_over_25 = float(np.sum(prob_matrix[grid > 2]))
        p_under_25 = float(np.sum(prob_matrix[grid <= 2]))

        p_btts_yes = float(np.sum(prob_matrix[1:, 1:]))

        return {
            "home_win": p_home,
            "draw": p_draw,
            "away_win": p_away,
            "over_2.5": p_over_25,
            "under_2.5": p_under_25,
            "btts_yes": p_btts_yes,
            "btts_no": max(0.0, 1.0 - p_btts_yes)
        }


class EVCalculator:
    """Calcula con precisión matemática el Expected Value y Kelly Criterion."""

    @staticmethod
    def calculate_ev(model_prob: float, decimal_odds: float) -> float:
        if decimal_odds <= 1.0:
            return -1.0
        return (model_prob * decimal_odds) - 1.0

    @staticmethod
    def calculate_kelly(model_prob: float, decimal_odds: float,
                        fraction: float = KELLY_FRACTION) -> float:
        b = decimal_odds - 1.0
        if b <= 0:
            return 0.0

        p = model_prob
        q = max(0.0, 1.0 - p)

        kelly = (b * p - q) / b
        kelly_fractional = kelly * fraction

        return max(0.0, min(kelly_fractional, 0.10))

    @staticmethod
    def calculate_brier_score(predictions: list, outcomes: list) -> float:
        if not predictions or not outcomes or len(predictions) != len(outcomes):
            return 0.25
        pred_arr = np.asarray(predictions)
        out_arr = np.asarray(outcomes)
        return float(np.mean((pred_arr - out_arr) ** 2))


class FormAdjuster:
    """Ajusta probabilidades combinando forma reciente e historial de forma segura."""

    def __init__(self):
        self.historical_weights = {}
        self._load_weights()

    def _load_weights(self):
        weights_file = os.path.join(MODEL_DIR, "learned_weights.pkl")
        if os.path.exists(weights_file):
            try:
                with open(weights_file, "rb") as f:
                    self.historical_weights = pickle.load(f)
            except Exception as e:
                logger.error("Error al cargar pesos históricos desde %s: %s", weights_file, e, exc_info=True)
                self.historical_weights = {}

    def save_weights(self):
        try:
            os.makedirs(MODEL_DIR, exist_ok=True)
            weights_file = os.path.join(MODEL_DIR, "learned_weights.pkl")
            with open(weights_file, "wb") as f:
                pickle.dump(self.historical_weights, f)
        except Exception as e:
            logger.error("Error al guardar pesos históricos en %s: %s", MODEL_DIR, e, exc_info=True)

    def adjust_probability(self, base_prob: float, team_features: dict,
                           h2h_data: list = None) -> float:
        adjustment = 0.0

        form_points = team_features.get("form_points", 7.5)
        form_factor = (form_points - 7.5) / 15.0
        adjustment += form_factor * 0.08

        if h2h_data and len(h2h_data) >= 3:
            team_id = team_features.get("team_id")
            if team_id is not None:
                h2h_wins = 0
                for m in h2h_data:
                    try:
                        home_team = m.get("teams", {}).get("home", {})
                        away_team = m.get("teams", {}).get("away", {})
                        if home_team.get("id") == team_id and home_team.get("winner"):
                            h2h_wins += 1
                        elif away_team.get("id") == team_id and away_team.get("winner"):
                            h2h_wins += 1
                    except Exception as e:
                        logger.warning("Error procesando registro individual de H2H: %s", e, exc_info=True)
                        continue
                h2h_rate = h2h_wins / len(h2h_data)
                h2h_factor = (h2h_rate - 0.33) * 0.06
                adjustment += h2h_factor

        adjusted = base_prob + adjustment
        return max(0.05, min(adjusted, 0.95))


def evaluate_pick(model_prob: float, odds: float) -> dict:
    """Evalúa las métricas financieras del pick objetivo."""
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
    poisson_model = PoissonGoalModel()
    
    result = poisson_model.predict_goals(
        home_attack=1.8,
        home_defense=0.7,
        away_attack=1.4,
        away_defense=1.2,
        league_avg_goals=2.5
    )
    
    probs = poisson_model.get_match_probabilities(result["prob_matrix"])
    logger.info(f"Lambda Local: {result['lambda_home']:.2f}")
    logger.info(f"Lambda Visitante: {result['lambda_away']:.2f}")
    logger.info(f"Probabilidades: Home {probs['home_win']:.2%} | Draw {probs['draw']:.2%} | Away {probs['away_win']:.2%}")
    logger.info(f"Over 2.5: {probs['over_2.5']:.2%} | Under 2.5: {probs['under_2.5']:.2%}")
    
    pick = evaluate_pick(probs["home_win"], 1.85)
    logger.info(f"\nPick: Local gana @ 1.85")
    logger.info(f"  EV: {pick['ev_pct']} | Kelly: {pick['kelly_pct']} | Valor: {pick['is_value_bet']}")