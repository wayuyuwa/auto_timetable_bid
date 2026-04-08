"""
Request-based scraper.
"""

from .beautifulsoup_scraper import BeautifulSoupScraper


class RequestScraper(BeautifulSoupScraper):
    """Thin alias for the existing requests + bs4 implementation."""

    pass
