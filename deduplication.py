import json
import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Dict, Any

# Configuración del logger para el módulo
logger = logging.getLogger(__name__)

# Configuración de entorno de ejecución e importaciones dinámicas robustas
CURRENT_DIR = Path(__file__).resolve().parent
PARENT_DIR = CURRENT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.append(str(PARENT_DIR))

try:
    from config import PICKS_DIR, MIN_EV_REEMISSION
except ImportError as e:
    logger.warning("No se pudo importar 'config'. Se usarán los valores por defecto. Detalle: %s", e)
    PICKS_DIR = str(CURRENT_DIR / "picks_diarios")
    MIN_EV_REEMISSION = 0.05

try:
    MIN_EV_REEMISSION = float(MIN_EV_REEMISSION)
except (ValueError, TypeError) as e:
    logger.error("Error al convertir MIN_EV_REEMISSION a float: %s. Reestableciendo a 0.05.", e)
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
                logger.info("Directorio de picks creado exitosamente en: %s", self.picks_dir)
                return picks
        except OSError as e:
            logger.error("Error de sistema de archivos al verificar/crear el directorio %s: %s", self.picks_dir, e)
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
                except (json.JSONDecodeError, IOError, TypeError) as e:
                    logger.warning("Error al leer o parsear el archivo de picks '%s': %s", filepath, e)
                    continue
        except OSError as e:
            logger.error("Error de E/S al buscar archivos con el patrón '%s' en '%s': %s", pattern, self.picks_dir, e)

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
            logger.warning("Se intentó evaluar un pick con un tipo de dato inválido: %s", type(pick))
            return "duplicate"

        key = self._make_key(pick)
        if not key:
            logger.warning("No se pudo generar una clave para el pick evaluado: %s", pick)
            return "duplicate"

        with self._lock:
            if key not in self.today_picks:
                return "new"

            existing = self.today_picks[key]

            try:
                existing_ev = float(existing.get("ev", 0.0) or 0.0)
            except (ValueError, TypeError) as e:
                logger.error("Error al convertir el EV existente a float para la clave '%s': %s", key, e)
                existing_ev = 0.0

            try:
                new_ev = float(pick.get("ev", 0.0) or 0.0)
            except (ValueError, TypeError) as e:
                logger.error("Error al convertir el nuevo EV a float para la clave '%s': %s", key, e)
                new_ev = 0.0

            ev_improvement = new_ev - existing_ev
            if ev_improvement >= MIN_EV_REEMISSION:
                logger.info("Pick mejorado detectado para clave '%s'. Incremento de EV: %.4f", key, ev_improvement)
                return "improved"

            return "duplicate"

    def register_pick(self, pick: dict) -> None:
        """Registra un nuevo pick de forma segura en memoria."""
        if not isinstance(pick, dict):
            logger.warning("Se intentó registrar un pick inválido: %s", type(pick))
            return
        key = self._make_key(pick)
        if not key:
            logger.warning("No se pudo generar clave para el registro del pick: %s", pick)
            return

        with self._lock:
            self.today_picks[key] = pick
            logger.info("Pick registrado exitosamente en memoria para la clave '%s'", key)

    def update_pick(self, pick: dict) -> None:
        """Actualiza la información de un pick previamente registrado guardando auditoría de EV."""
        if not isinstance(pick, dict):
            logger.warning("Se intentó actualizar un pick inválido: %s", type(pick))
            return
        key = self._make_key(pick)
        if not key:
            logger.warning("No se pudo generar clave para la actualización del pick: %s", pick)
            return

        with self._lock:
            try:
                prev_ev_raw = self.today_picks.get(key, {}).get("ev", 0.0)
                prev_ev = float(prev_ev_raw or 0.0)
            except (ValueError, TypeError) as e:
                logger.error("Error al parsear el EV previo durante la actualización para la clave '%s': %s", key, e)
                prev_ev = 0.0

            pick_copy = pick.copy()
            pick_copy["_updated_at"] = datetime.now().isoformat()
            pick_copy["_previous_ev"] = prev_ev
            self.today_picks[key] = pick_copy
            logger.info("Pick actualizado exitosamente con auditoría para la clave '%s'", key)

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
                except (ValueError, TypeError) as e:
                    logger.warning("Error al convertir EV en el resumen de picks diarios para el elemento %s: %s", p, e)
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
                    except OSError as e:
                        logger.error("No se pudo eliminar el archivo '%s' durante la purga diaria: %s", f, e)
                        pass
            self.today_picks.clear()
            logger.info("Purga diaria completada con éxito. Datos en memoria limpiados.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    dedup = DeduplicationManager()
    logger.info("Picks de hoy: %d", dedup.get_today_count())
    summary = dedup.get_today_summary()
    logger.info("Partidos cubiertos: %d", summary['matches_covered'])
    logger.info("EV promedio: %.4f", summary['avg_ev'])