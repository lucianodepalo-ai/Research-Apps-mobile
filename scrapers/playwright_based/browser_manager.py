"""
Browser manager para scrapers Tier 4 (redes sociales con Playwright).

Aplica medidas anti-detección estándar:
- User agents realistas
- Viewport común (1920x1080)
- Idioma es-AR
- Timezone Argentina
- Stealth scripts (webdriver=undefined, plugins, etc.)
- Proxy opcional

Para usar redes sociales con login:
- Usar cuentas DEDICADAS (nunca personales)
- Idealmente con proxy residencial
- Aceptar que las cuentas se pueden banear
"""
import random
from typing import Optional
from contextlib import contextmanager
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

from config.settings import HEADLESS, USE_PROXY, PROXY_URL


REALISTIC_USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Chrome macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
]


# Script que se inyecta antes de cargar páginas para ocultar Playwright.
STEALTH_SCRIPT = """
// Ocultar webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Plugins fake
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin' },
        { name: 'Chrome PDF Viewer' },
        { name: 'Native Client' }
    ]
});

// Idiomas
Object.defineProperty(navigator, 'languages', {
    get: () => ['es-AR', 'es', 'en']
});

// Plataforma
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });

// Permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
"""


class BrowserManager:
    """Wrapper para crear contextos de browser con anti-detección."""

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        launch_args = {
            "headless": HEADLESS,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }
        if USE_PROXY and PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}

        self._browser = self._playwright.chromium.launch(**launch_args)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    @contextmanager
    def new_context(self, storage_state: Optional[str] = None) -> BrowserContext:
        """
        Crea contexto con configuración argentina y anti-detección.
        storage_state: ruta a JSON con cookies/localStorage para reutilizar sesión.
        """
        ua = random.choice(REALISTIC_USER_AGENTS)
        context_args = {
            "user_agent": ua,
            "viewport": {"width": 1920, "height": 1080},
            "locale": "es-AR",
            "timezone_id": "America/Argentina/Buenos_Aires",
            "geolocation": {"latitude": -34.6037, "longitude": -58.3816},
            "permissions": ["geolocation"],
        }
        if storage_state:
            context_args["storage_state"] = storage_state

        ctx = self._browser.new_context(**context_args)
        ctx.add_init_script(STEALTH_SCRIPT)
        try:
            yield ctx
        finally:
            ctx.close()

    @contextmanager
    def new_page(self, storage_state: Optional[str] = None) -> Page:
        """Atajo para ir directo a una page."""
        with self.new_context(storage_state=storage_state) as ctx:
            page = ctx.new_page()
            yield page
