"""
CAPTCHA solving utility using ddddocr.
"""

import ddddocr
import logging

# Configure logging
logger = logging.getLogger(__name__)

class CaptchaSolver:
    """CAPTCHA solver using ddddocr."""
    
    def __init__(self):
        """Initialize the OCR engine."""
        self.ocr = ddddocr.DdddOcr(show_ad=False)
    
    def solve(self, image: bytes) -> str:
        """
        Solve CAPTCHA from image bytes with retry mechanism.
        
        Args:
            image (bytes): CAPTCHA image data
            
        Returns:
            str: Solved CAPTCHA text
        """
        
        try:
            return self.ocr.classification(image)
        except Exception as e:
            logger.error(f"Unexpected error during CAPTCHA solving: {str(e)}")
            raise