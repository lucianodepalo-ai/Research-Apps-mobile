"""
Cliente Ollama: wrapper liviano sobre la API HTTP.

Filosofía:
- Si Ollama está caído, no rompemos nada: devolvemos None y el caller
  hace fallback a heurísticas simples
- Cacheamos respuestas por hash del prompt para no gastar tokens repetidos
- Timeout corto: si Ollama está lento, mejor seguir sin él que bloquear todo

Setup en Hetzner:
    curl -fsSL https://ollama.com/install.sh | sh
    systemctl enable ollama && systemctl start ollama
    ollama pull llama3.2:3b   # 2GB, suficiente para clasificar reviews

En .env:
    OLLAMA_URL=http://localhost:11434
    OLLAMA_MODEL=llama3.2:3b
    OLLAMA_ENABLED=true
"""
import json
import hashlib
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any

import httpx
from loguru import logger

from config.settings import DATA_DIR
import os


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "true").lower() == "true"
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT_SEC", "30"))

CACHE_DB = DATA_DIR / "ollama_cache.db"


class OllamaClient:
    """Cliente con cache, health check y fallback automático."""

    def __init__(self, url: str = None, model: str = None):
        self.url = url or OLLAMA_URL
        self.model = model or OLLAMA_MODEL
        self.enabled = OLLAMA_ENABLED
        self._healthy: Optional[bool] = None
        self._init_cache()

    def _init_cache(self):
        """SQLite de cache: hash(prompt+model) -> response."""
        self._conn = sqlite3.connect(str(CACHE_DB), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                response TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def _cache_key(self, prompt: str) -> str:
        return hashlib.sha1(f"{self.model}:{prompt}".encode()).hexdigest()

    def _cache_get(self, prompt: str) -> Optional[str]:
        cur = self._conn.execute(
            "SELECT response FROM cache WHERE key = ?",
            (self._cache_key(prompt),)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def _cache_set(self, prompt: str, response: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, response) VALUES (?, ?)",
            (self._cache_key(prompt), response)
        )
        self._conn.commit()

    def health_check(self, force: bool = False) -> bool:
        """Verifica que Ollama responda. Cachea el resultado por la sesión."""
        if not self.enabled:
            return False
        if self._healthy is not None and not force:
            return self._healthy
        try:
            r = httpx.get(f"{self.url}/api/tags", timeout=5)
            self._healthy = r.status_code == 200
            if self._healthy:
                logger.debug(f"Ollama OK en {self.url} (modelo {self.model})")
            else:
                logger.warning(f"Ollama responde pero status {r.status_code}")
        except Exception as e:
            logger.warning(f"Ollama no responde en {self.url}: {e}")
            self._healthy = False
        return self._healthy

    def generate(self, prompt: str, *, json_mode: bool = False,
                 use_cache: bool = True) -> Optional[str]:
        """
        Genera respuesta. Devuelve None si Ollama está caído.
        json_mode=True fuerza respuesta JSON.
        """
        if not self.health_check():
            return None

        if use_cache:
            cached = self._cache_get(prompt)
            if cached is not None:
                return cached

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,    # bajo: queremos consistencia
                "num_predict": 500,
            },
        }
        if json_mode:
            payload["format"] = "json"

        try:
            r = httpx.post(
                f"{self.url}/api/generate",
                json=payload,
                timeout=OLLAMA_TIMEOUT,
            )
            r.raise_for_status()
            response = r.json().get("response", "").strip()
            if use_cache:
                self._cache_set(prompt, response)
            return response
        except httpx.TimeoutException:
            logger.warning(f"Ollama timeout (>{OLLAMA_TIMEOUT}s)")
            return None
        except Exception as e:
            logger.warning(f"Ollama error: {e}")
            return None

    def generate_json(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Wrapper que parsea la respuesta como JSON."""
        raw = self.generate(prompt, json_mode=True)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"Ollama devolvió JSON inválido: {e}")
            return None


# Singleton perezoso
_client: Optional[OllamaClient] = None

def get_client() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client
