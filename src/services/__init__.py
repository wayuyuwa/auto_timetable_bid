"""
Services layer for business logic.
"""

from .bidding_service import BiddingService

# BiddingWorker (src/services/worker_thread.py) is only used by the legacy
# PyQt5 GUI in src/gui and is not imported here so the pywebview app never
# loads Qt.
__all__ = ['BiddingService']
