"""
deduplication.py - Sistema Anti-Spam y Deduplicación
Verifica picks_diarios antes de emitir para evitar duplicados en Telegram.
Excepción: Re-emisión si el EV mejoró significativamente.
"""

import json
import os
import glob
from datetime import datetime
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import PICKS_DIR, MIN_EV_REEMISSION


class DeduplicationManager:
    """Gestiona la deduplicación de picks dentro del mismo día."""

    def __init__(self):
        self.today_picks = self._load_today_picks()

    def _load_today_picks(self) -> dict:
        """
        Carga todos los picks emitidos hoy desde picks_diarios/.
        Returns dict con clave = match_market y valor = pick data.
        """
        picks = {}
        today_str = datetime.now().strftime("%Y%m%d")

        if not os.path.exists(PICKS_DIR):
            os.makedirs(PICKS_DIR, exist_ok=True)
            return picks

        pattern = os.path.join(PICKS_DIR, f"picks_{today_str}_*.json")
        files = glob.glob(pattern)

        for filepath in files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    file_picks = json.load(f)
                    for pick in file_picks:
                        key = self._make_key(pick)
                        picks[key] = pick
            except (json.JSONDecodeError, IOError):
                continue

        return picks

    def _make_key(self, pick: dict) -> str:
        """Genera clave única para un pick: match + market."""
        match = pick.get("match", "").lower().replace(" ", "")
        market = pick.get("market", "").lower().replace(" ", "")
        return f"{match}_{market}"

    def check_pick(self, pick: dict) -> str:
        """
        Verifica el estado de un pick.
        
        Returns:
            "new" - Pick no existe, se puede enviar
            "duplicate" - Pick ya enviado hoy, no enviar
            "improved" - Pick existe pero EV mejoró significativamente
        """
        key = self._make_key(pick)

        if key not in self.today_picks:
            return "new"

        existing = self.today_picks[key]
        existing_ev = existing.get("ev", 0)
        new_ev = pick.get("ev", 0)

        # Excepción de valor: re-emitir si EV mejoró significativamente
        ev_improvement = new_ev - existing_ev
        if ev_improvement >= MIN_EV_REEMISSION:
            return "improved"

        return "duplicate"

    def register_pick(self, pick: dict):
        """Registra un pick nuevo en la memoria del día."""
        key = self._make_key(pick)
        self.today_picks[key] = pick

    def update_pick(self, pick: dict):
        """Actualiza un pick existente (re-emisión por mejora de EV)."""
        key = self._make_key(pick)
        pick["_updated_at"] = datetime.now().isoformat()
        pick["_previous_ev"] = self.today_picks.get(key, {}).get("ev", 0)
        self.today_picks[key] = pick

    def get_today_count(self) -> int:
        """Retorna la cantidad de picks emitidos hoy."""
        return len(self.today_picks)

    def get_today_summary(self) -> dict:
        """Retorna resumen de picks del día."""
        return {
            "total_picks": len(self.today_picks),
            "matches_covered": len(set(p.get("match", "") for p in self.today_picks.values())),
            "avg_ev": sum(p.get("ev", 0) for p in self.today_picks.values()) / max(len(self.today_picks), 1),
            "picks": list(self.today_picks.values())
        }

    def clear_daily(self):
        """Limpia la carpeta picks_diarios (ejecutar al cierre de jornada)."""
        if os.path.exists(PICKS_DIR):
            for f in glob.glob(os.path.join(PICKS_DIR, "*.json")):
                os.remove(f)
        self.today_picks = {}


if __name__ == "__main__":
    dedup = DeduplicationManager()
    print(f"Picks de hoy: {dedup.get_today_count()}")
    summary = dedup.get_today_summary()
    print(f"Partidos cubiertos: {summary['matches_covered']}")
    print(f"EV promedio: {summary['avg_ev']:.4f}")
