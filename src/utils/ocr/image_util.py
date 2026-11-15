import numpy as np
from PIL import Image
import onnxruntime as ort
from io import BytesIO


class ImageUtil:
    """Image preprocessing utilities for OCR"""

    @staticmethod
    def load_as_tensor(image_input):
        """
        Load image and convert to ONNX tensor [1, 1, 64, W]
        
        Args:
            image_input: Path to the image file (str) or image bytes
            
        Returns:
            numpy array ready for ONNX inference
        """
        TARGET_HEIGHT = 64

        # Load image and convert to grayscale
        if isinstance(image_input, bytes):
            image = Image.open(BytesIO(image_input)).convert('L')
        else:
            image = Image.open(image_input).convert('L')
        
        # Calculate new width maintaining aspect ratio
        aspect_ratio = image.width / image.height
        new_width = int(TARGET_HEIGHT * aspect_ratio)
        
        # Resize image
        image = image.resize((new_width, TARGET_HEIGHT), Image.LANCZOS)
        
        # Convert to numpy array
        pixel_data = np.array(image, dtype=np.float32)
        
        # Normalize pixels: (pixel / 255 - 0.5) / 0.5
        normalized = (pixel_data / 255.0 - 0.5) / 0.5
        
        # Reshape to NCHW format [1, 1, height, width]
        tensor = normalized.reshape(1, 1, TARGET_HEIGHT, new_width)
        
        return tensor
