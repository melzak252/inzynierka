"""Small NoDriver wrapper used by bookmaker scrapers.

NoDriver is imported lazily so the rest of the betting app can be used before
the scraping dependency is installed.
"""

from __future__ import annotations

from pathlib import Path
import inspect
from typing import Any

from betting_app.core.config import load_config


class NoDriverClient:
    """Lifecycle helper for a NoDriver browser session."""

    def __init__(self, headless: bool | None = None, debug_dir: str | Path | None = None) -> None:
        cfg = load_config()
        self.headless = cfg.scraper_headless if headless is None else headless
        self.debug_dir = Path(debug_dir) if debug_dir else cfg.debug_dir
        self.browser: Any | None = None

    async def __aenter__(self) -> "NoDriverClient":
        """Start browser."""

        try:
            import nodriver as uc
        except ImportError as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("NoDriver is not installed. Install it with: pip install nodriver") from exc

        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.browser = await uc.start(headless=self.headless)
        return self

    async def __aexit__(self, exc_type: object, exc: BaseException | None, traceback: object) -> None:
        """Stop browser."""

        if self.browser is not None:
            result = self.browser.stop()
            if inspect.isawaitable(result):
                await result
            self.browser = None

    async def open(self, url: str) -> Any:
        """Open a URL in the active browser."""

        if self.browser is None:
            raise RuntimeError("Browser is not started")
        return await self.browser.get(url)

    async def save_debug_artifacts(self, tab: Any, prefix: str) -> tuple[str | None, str | None]:
        """Best-effort HTML/screenshot debug capture."""

        html_path = self.debug_dir / f"{prefix}.html"
        screenshot_path = self.debug_dir / f"{prefix}.png"
        saved_html: str | None = None
        saved_screenshot: str | None = None
        try:
            html = await tab.get_content()
            html_path.write_text(html, encoding="utf-8")
            saved_html = str(html_path)
        except Exception:
            saved_html = None
        try:
            await tab.save_screenshot(str(screenshot_path))
            saved_screenshot = str(screenshot_path)
        except Exception:
            saved_screenshot = None
        return saved_html, saved_screenshot
