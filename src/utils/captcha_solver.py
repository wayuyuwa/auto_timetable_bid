"""
CAPTCHA solving utility using ddddocr.
"""

import ddddocr
from PIL import Image

# Fix for newer PIL versions
if not hasattr(Image, 'ANTIALIAS'):
    setattr(Image, 'ANTIALIAS', Image.LANCZOS)

class CaptchaSolver:
    """CAPTCHA solver using ddddocr."""
    
    def __init__(self):
        """Initialize the OCR engine."""
        self.ocr = ddddocr.DdddOcr()
    
    def solve(self, image: bytes) -> str:
        """
        Solve CAPTCHA from image bytes.
        
        Args:
            image (bytes): CAPTCHA image data
            
        Returns:
            str: Solved CAPTCHA text
        """
        return self.ocr.classification(image) 