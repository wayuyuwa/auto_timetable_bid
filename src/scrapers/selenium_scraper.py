"""
Backward compatibility shim.

Legacy imports of SeleniumScraper now resolve to PlaywrightScraper.
"""

from .playwright_scraper import PlaywrightScraper


class SeleniumScraper(PlaywrightScraper):
    """Alias class kept for legacy compatibility during migration."""

    pass
