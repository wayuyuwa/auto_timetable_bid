"""
CAPTCHA solving utility using ddddocr.
"""

import logging

# Configure logging
logger = logging.getLogger(__name__)

class CaptchaSolver:
    """CAPTCHA solver using ddddocr."""
    
    def __init__(self):
        """Create a solver without loading the optional ONNX runtime yet."""
        self.ocr = None
    
    def solve(self, image: bytes) -> str:
        """
        Solve CAPTCHA from image bytes with retry mechanism.
        
        Args:
            image (bytes): CAPTCHA image data
            
        Returns:
            str: Solved CAPTCHA text
        """
        
        try:
            if self.ocr is None:
                from .ocr.OCR import OCR

                self.ocr = OCR()
                self.ocr.init()
            return self.ocr.recognize(image)
        except Exception as e:
            logger.error(f"Unexpected error during CAPTCHA solving: {str(e)}")
            raise