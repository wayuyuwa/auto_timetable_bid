"""
CAPTCHA solving with the bundled ONNX OCR model.

The model is loaded once per process and shared by every scraper (loading it
costs ~1.5 s, plus ~3 s for the first onnxruntime/numpy import). warm_up()
loads it in the background at app start so the first login does not wait.
onnxruntime sessions are safe to run from several threads.
"""

import logging
import threading

# Configure logging
logger = logging.getLogger(__name__)

_shared_ocr = None
_lock = threading.Lock()


def _get_ocr():
    global _shared_ocr
    with _lock:
        if _shared_ocr is None:
            from .ocr.OCR import OCR

            ocr = OCR()
            ocr.init()
            _shared_ocr = ocr
        return _shared_ocr


def warm_up():
    """Load the OCR model on a background thread (no-op if already loaded)."""
    def load():
        try:
            _get_ocr()
        except Exception as error:  # noqa: BLE001 - solve() reports it later
            logger.warning("Captcha model warm-up failed: %s", error)

    threading.Thread(target=load, name="ocr-warm-up", daemon=True).start()


class CaptchaSolver:
    """CAPTCHA solver backed by the shared OCR model."""

    def solve(self, image: bytes) -> str:
        """Return the CAPTCHA text for image bytes (or a file path)."""
        try:
            return _get_ocr().recognize(image)
        except Exception as e:
            logger.error(f"Unexpected error during CAPTCHA solving: {str(e)}")
            raise
