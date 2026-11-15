import os
import json
import numpy as np
import onnxruntime as ort
from .image_util import ImageUtil

class OCR:
    """OCR class for text recognition using ONNX model"""

    def __init__(self):
        """
        Initialize OCR with model and charset paths
        
        Args:
            model_path: Path to ONNX model file
            charset_path: Path to charset JSON file
        """

        dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(dir, "common_old.onnx")
        charset_path = os.path.join(dir, "common_old_charset.json")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")
        self.model_path = model_path

        if not os.path.exists(charset_path):
            raise FileNotFoundError(f"Charset file not found: {charset_path}")
        self.charset = self._load_charset(charset_path)
        self.session = None

    @staticmethod
    def _load_charset(path):
        """Load charset from JSON file"""
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def init(self):
        """Initialize ONNX inference session"""
        self.session = ort.InferenceSession(self.model_path)

    def recognize(self, image):
        """
        Run OCR on image
        
        Args:
            image: Path to image file or image bytes
            
        Returns:
            Recognized text string
        """
        if self.session is None:
            raise RuntimeError('OCR not initialized. Call init() first.')

        input_tensor = ImageUtil.load_as_tensor(image)

        input_name = self.session.get_inputs()[0].name

        results = self.session.run(None, {input_name: input_tensor})
        output = results[0]

        return self._decode(output)

    def _decode(self, output_tensor):
        """
        CTC decode the model output
        
        Args:
            output_tensor: Model output tensor
            
        Returns:
            Decoded text string
        """
        indices = output_tensor.flatten().astype(int)

        # CTC rules: remove duplicates & blanks (index 0)
        result = ''
        last = -1

        for idx in indices:
            if idx != 0 and idx != last:
                if idx < len(self.charset):
                    result += self.charset[idx]
            last = idx

        return result
