"""
Base class para todos los scrapers.
Maneja: logging, retries, delays, auditoría en DB.
"""
import time
import random
import traceback
from abc import ABC, abstractmethod
from typing import List, Dict
from loguru import logger
from config.settings import LOG_DIR, MIN_DELAY_SEC, MAX_DELAY_SEC, MAX_RETRIES
from database.repository import start_run, finish_run, save_signals_bulk


class BaseScraper(ABC):
    """
    Todos los scrapers heredan de acá.
    Cada uno implementa fetch() que debe retornar List[Dict] con señales.
    """

    name: str = "base"
    tier: int = 1   # 1=API oficial, 2=suggest, 3=scraping respetuoso, 4=playwright

    def __init__(self):
        self.run_id = None
        self.errors = []
        self._setup_logger()

    def _setup_logger(self):
        log_path = LOG_DIR / f"{self.name}.log"
        logger.add(
            log_path,
            rotation="10 MB",
            retention="30 days",
            level="INFO",
            filter=lambda rec: rec["extra"].get("scraper") == self.name,
        )
        self.log = logger.bind(scraper=self.name)

    def random_delay(self):
        """Delay aleatorio entre requests para no parecer bot."""
        delay = random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)
        time.sleep(delay)

    def with_retries(self, fn, *args, **kwargs):
        """Ejecuta una función con retries y backoff exponencial."""
        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_exc = e
                wait = 2 ** attempt
                self.log.warning(
                    f"[{self.name}] intento {attempt}/{MAX_RETRIES} falló: {e}. "
                    f"Reintentando en {wait}s..."
                )
                time.sleep(wait)
        raise last_exc

    @abstractmethod
    def fetch(self) -> List[Dict]:
        """
        Cada scraper implementa esto. Debe retornar lista de dicts con:
        - source (obligatorio)
        - term (obligatorio)
        - opcional: score, volume, category, url, extra, etc.
        """
        ...

    def run(self) -> int:
        """Ciclo completo: start_run -> fetch -> save -> finish_run."""
        self.run_id = start_run(self.name)
        self.log.info(f"=== Iniciando {self.name} (run_id={self.run_id}) ===")
        items = []
        status = "success"
        try:
            items = self.fetch()
            saved = save_signals_bulk(items) if items else 0
            self.log.info(f"✅ {self.name}: {saved} señales guardadas")
        except Exception as e:
            status = "failed"
            err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            self.errors.append(err)
            self.log.error(f"❌ {self.name} falló: {err}")
        finally:
            finish_run(
                self.run_id,
                status,
                items=len(items),
                errors=len(self.errors),
                error_log="\n".join(self.errors) if self.errors else None,
            )
        return len(items)
