"""
Worker thread management for running services in background threads.
"""

from PyQt5.QtCore import QThread, pyqtSignal
from typing import Any, Callable
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class BiddingWorker(QThread):
    """Worker thread that executes service operations in the background."""
    
    # Signal emitted when operation completes
    operation_finished = pyqtSignal()
    
    def __init__(self, service_method: Callable, *args, **kwargs):
        """
        Initialize the worker thread.
        
        Args:
            service_method: The method to call (e.g., service.login, service.bid_courses)
            *args: Positional arguments to pass to the method
            **kwargs: Keyword arguments to pass to the method
        """
        super().__init__()
        self.service_method = service_method
        self.args = args
        self.kwargs = kwargs
        logger.debug(f"Worker initialized for {service_method.__name__}")
    
    def run(self):
        """Execute the service method in a separate thread."""
        try:
            logger.debug(f"Worker starting: {self.service_method.__name__}")
            self.service_method(*self.args, **self.kwargs)
            logger.debug(f"Worker completed: {self.service_method.__name__}")
        except Exception as e:
            logger.error(f"Worker thread error in {self.service_method.__name__}: {e}")
        finally:
            self.operation_finished.emit()


class WorkerThreadManager:
    """Manages worker threads to ensure proper cleanup and tracking."""
    
    def __init__(self):
        """Initialize the thread manager."""
        self.active_threads = []
        logger.debug("WorkerThreadManager initialized")
    
    def start_worker(self, service_method: Callable, *args, **kwargs) -> BiddingWorker:
        """
        Start a new worker thread.
        
        Args:
            service_method: The method to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            BiddingWorker: The created worker thread
        """
        worker = BiddingWorker(service_method, *args, **kwargs)
        worker.operation_finished.connect(lambda: self._on_worker_finished(worker))
        self.active_threads.append(worker)
        worker.start()
        logger.info(f"Started worker thread for {service_method.__name__}")
        return worker
    
    def _on_worker_finished(self, worker: BiddingWorker):
        """
        Handle worker thread completion.
        
        Args:
            worker: The worker that finished
        """
        if worker in self.active_threads:
            self.active_threads.remove(worker)
        logger.debug(f"Worker removed from active threads. Remaining: {len(self.active_threads)}")
    
    def stop_all(self, timeout_ms: int = 15000):
        """Wait for active workers after their service cancellation was requested."""
        logger.info(f"Stopping {len(self.active_threads)} active worker threads")
        for worker in self.active_threads[:]:  # Copy list to avoid modification during iteration
            if worker.isRunning():
                worker.quit()
                if not worker.wait(timeout_ms):
                    logger.warning("Worker did not finish within %s ms", timeout_ms)
        self.active_threads[:] = [
            worker for worker in self.active_threads if worker.isRunning()
        ]
    
    def has_active_threads(self) -> bool:
        """
        Check if there are any active threads.
        
        Returns:
            bool: True if there are active threads
        """
        return len(self.active_threads) > 0
    
    def cleanup(self):
        """Clean up all threads."""
        self.stop_all()
        logger.info("WorkerThreadManager cleaned up")
