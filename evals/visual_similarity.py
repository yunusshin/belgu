"""Run with .venv/bin/python evals/visual_similarity.py; no network or database."""
from io import BytesIO
import json
from pathlib import Path
from time import perf_counter
from PIL import Image
from belgu.core.visual_similarity import compare_images


def encode(image, fmt='PNG'):
    output = BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def benchmark():
    assets = Path(__file__).resolve().parents[1] / 'src/belgu/demo/assets'
    reference = (assets/'fictional-reference.png').read_bytes()
    image = Image.open(BytesIO(reference)).convert('RGB')
    shifted = Image.new('RGB', image.size, 'white')
    shifted.paste(image, (80, 50))
    candidates = {
        'identical': reference,
        'jpeg_reencoded': encode(image, 'JPEG'),
        'resized_75_percent': encode(image.resize((image.width*3//4, image.height*3//4))),
        'layout_shift_80_50': encode(shifted),
        'distinct_fictional_login': (assets/'fictional-login.png').read_bytes(),
        'blank': encode(Image.new('RGB', image.size, 'white')),
        'portrait_geometry': encode(image.resize((390, 844))),
        'unreadable': b'not-an-image',
    }
    results = {}
    for name, candidate in candidates.items():
        start = perf_counter()
        result = compare_images(reference, candidate)
        results[name] = {**result, 'elapsed_ms': round((perf_counter()-start)*1000, 2)}
    return results


if __name__ == '__main__':
    print(json.dumps(benchmark(), ensure_ascii=False, indent=2))
