import time
from OCR import OCR


def main():
    ocr = OCR()
    ocr.init()

    # Start timing
    start = time.perf_counter()

    text = ocr.recognize('src/utils/ocr/Kaptcha.jpg')

    # End timing
    end = time.perf_counter()

    time_ms = (end - start) * 1000

    print(f'OCR result: {text}')
    print(f'Time consumed: {time_ms:.2f} ms')


if __name__ == '__main__':
    main()
