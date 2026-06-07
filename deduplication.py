import json
import os
import sys
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Dict, Any

# Configuración de entorno de ejecución e importaciones dinámicas robustas
CURRENT_DIR = Path(__file__).resolve().parent
PARENT_DIR = CURRENT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.append(str(PARENT_DIR))

try:
    from config import PICKS_DIR, MIN_EV_REEMISSION
except ImportError:
    PICKS_DIR = str(CURRENT_DIR / "picks_diarios")
    MIN_EV_REEMISSION = 0.05

try:
    MIN_EV_REEMISSION = float(MIN_EV_REEMISSION)
except (ValueError, TypeError):
    MIN_EV_REEMISSION = 0.05


class DeduplicationManager:
    """Gestiona la deduplicación de picks en la misma jornada de forma segura y eficiente."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.picks_dir = Path(PICKS_DIR)
        self.today_picks: Dict[str, dict] = {}
        self.reload_picks()

    def reload_picks(self) -> None:
        """Sincroniza el estado en memoria con el almacenamiento físico."""
        with self._lock:
            self.today_picks = self._load_today_picks()

    def _load_today_picks(self) -> Dict[str, dict]:
        """Carga y valida los picks emitidos en el día actual."""
        picks: Dict[str, dict] = {}
        today_str = datetime.now().strftime("%Y%m%d")

        try:
            if not self.picks_dir.exists():
                self.picks_dir.mkdir(parents=True, exist_ok=True)
                return picks
        except OSError:
            return picks

        pattern = f"picks_{today_str}_*.json"
        try:
            for filepath in self.picks_dir.glob(pattern):
                try:
                    with filepath.open("r", encoding="utf-8") as f:
                        file_picks = json.load(f)
                        if isinstance(file_picks, list):
                            for pick in file_picks:
                                if isinstance(pick, dict):
                                    key = self._make_key(pick)
                                    if key:
                                        picks[key] = pick
                except (json.JSONDecodeError, IOError, TypeError):
                    continue
        except OSError:
            pass

        return picks

    def _make_key(self, pick: dict) -> str:
        """Genera una clave única normalizada para evitar colisiones semánticas."""
        if not isinstance(pick, dict):
            return ""

        raw_match = pick.get("match")
        raw_market = pick.get("market")

        match_str = str(raw_match).lower() if raw_match is not None else ""
        market_str = str(raw_market).lower() if raw_market is not None else ""

        match_clean = "".join(match_str.split())
        market_clean = "".join(market_str.split())

        if not match_clean and not market_clean:
            return ""

        return f"{match_clean}_{market_clean}"

    def check_pick(self, pick: dict) -> str:
        """
        Evalúa el estado del pick propuesto frente a los ya procesados.

        Returns:
            "new" - Pick inédito, apto para envío.
            "duplicate" - Pick ya enviado con métricas similares o inferiores.
            "improved" - Ya enviado, pero el EV actual supera al anterior significativamente.
        """
        if not isinstance(pick, dict):
            return "duplicate"

        key = self._make_key(pick)
        if not key:
            return "duplicate"

        with self._lock:
            if key not in self.today_picks:
                return "new"

            existing = self.today_picks[key]

            try:
                existing_ev = float(existing.get("ev", 0.0) or 0.0)
            except (ValueError, TypeError):
                existing_ev = 0.0

            try:
                new_ev = float(pick.get("ev", 0.0) or 0.0)
            except (ValueError, TypeError):
                new_ev = 0.0

            ev_improvement = new_ev - existing_ev
            if ev_improvement >= MIN_EV_REEMISSION:
                return "improved"

            return "duplicate"

    def register_pick(self, pick: dict) -> None:
        """Registra un nuevo pick de forma segura en memoria."""
        if not isinstance(pick, dict):
            return
        key = self._make_key(pick)
        if not key:
            return

        with self._lock:
            self.today_picks[key] = pick

    def update_pick(self, pick: dict) -> None:
        """Actualiza la información de un pick previamente registrado guardando auditoría de EV."""
        if not isinstance(pick, dict):
            return
        key = self._make_key(pick)
        if not key:
            return

        with self._lock:
            try:
                prev_ev_raw = self.today_picks.get(key, {}).get("ev", 0.0)
                prev_ev = float(prev_ev_raw or 0.0)
            except (ValueError, TypeError):
                prev_ev = 0.0

            pick_copy = pick.copy()
            pick_copy["_updated_at"] = datetime.now().isoformat()
            pick_copy["_previous_ev"] = prev_ev
            self.today_picks[key] = pick_copy

    def get_today_count(self) -> int:
        """Obtiene la cantidad total de picks procesados en el día actual."""
        with self._lock:
            return len(self.today_picks)

    def get_today_summary(self) -> dict:
        """Genera un reporte analítico del estado actual de las emisiones diarias."""
        with self._lock:
            total_picks = len(self.today_picks)
            if total_picks == 0:
                return {
                    "total_picks": 0,
                    "matches_covered": 0,
                    "avg_ev": 0.0,
                    "picks": []
                }

            matches = set()
            ev_sum = 0.0
            picks_list = []

            for p in self.today_picks.values():
                match_val = p.get("match")
                if match_val is not None:
                    matches.add(str(match_val).strip())
                
                try:
                    ev_sum += float(p.get("ev", 0.0) or 0.0)
                except (ValueError, TypeError):
                    pass
                
                picks_list.append(p)

            return {
                "total_picks": total_picks,
                "matches_covered": len(matches),
                "avg_ev": ev_sum / total_picks,
                "picks": picks_list
            }

    def clear_daily(self) -> None:
        """Realiza la purga de archivos y limpia el estado del sistema en memoria."""
        with self._lock:
            if self.picks_dir.exists():
                for f in self.picks_dir.glob("*.json"):
                    try:
                        f.unlink(missing_ok=True)
                    except OSError:
                        pass
            self.today_picks.clear()


if __name__ == "__main__":
    dedup = DeduplicationManager()
    print(f"Picks de hoy: {dedup.get_today_count()}")
    summary = dedup.get_today_summary()
    print(f"Partidos cubiertos: {summary['matches_covered']}")
    print(f"EV promedio: {summary['avg_ev']:.4f}")