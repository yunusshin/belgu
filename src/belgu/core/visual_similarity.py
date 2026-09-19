"""Local whole-viewport image heuristics; scores are leads, never probabilities."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from math import cos, pi, sqrt
from statistics import median
import warnings

from PIL import Image, ImageChops, ImageOps, ImageStat, UnidentifiedImageError

METHOD_VERSION = 'local-phash-edge-rgb-v1'
MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 16_000_000
_COS = [[cos((2*x+1)*u*pi/64) for x in range(32)] for u in range(8)]
NORMALIZATION = 'EXIF orientation; white alpha composite; equal aspect (within 3%); Lanczos resize, no crop.'


def _read(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise ValueError('missing_or_oversize')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as raw:
                if raw.width*raw.height > MAX_PIXELS or min(raw.size) < 32:
                    raise ValueError('unreasonable_dimensions')
                oriented = ImageOps.exif_transpose(raw)
                rgba = oriented.convert('RGBA')
                image = Image.new('RGBA', rgba.size, 'white')
                image.alpha_composite(rgba)
                return image.convert('RGB')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('unreadable') from exc


def _pixels(image):
    return list(image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata())


def _features(image):
    gray = image.convert('L').resize((256, 192), Image.Resampling.LANCZOS)
    horizontal = ImageChops.difference(gray.crop((1, 0, 256, 191)), gray.crop((0, 0, 255, 191)))
    vertical = ImageChops.difference(gray.crop((0, 1, 255, 192)), gray.crop((0, 0, 255, 191)))
    edge = ImageChops.lighter(horizontal, vertical)
    if ImageStat.Stat(gray).stddev[0] < 3 or ImageStat.Stat(edge).mean[0] < .3:
        raise ValueError('low_detail')
    structure = _pixels(edge.resize((16, 12), Image.Resampling.BOX))
    small = gray.resize((32, 32), Image.Resampling.LANCZOS)
    pixels = _pixels(small)
    rows = [[sum(pixels[y*32+x]*_COS[u][x] for x in range(32)) for u in range(8)] for y in range(32)]
    dct = [sum(rows[y][u]*_COS[v][y] for y in range(32)) for v in range(8) for u in range(8) if u or v]
    midpoint = median(dct)
    phash = [value > midpoint for value in dct]
    colors = _pixels(image.resize((16, 12), Image.Resampling.BOX))
    return phash, structure, colors


def compare_images(reference_bytes: bytes, candidate_bytes: bytes) -> dict:
    result = {'method_version': METHOD_VERSION, 'status': 'unassessed', 'score': None,
              'components': {}, 'normalization': NORMALIZATION,
              'limitations': ['Whole-page visual heuristic, not logo recognition, attribution or maliciousness probability.',
                              'Responsive layout, theme, overlays and capture timing can change the score.']}
    try:
        reference, candidate = _read(reference_bytes), _read(candidate_bytes)
        result['dimensions'] = {'reference': list(reference.size), 'candidate': list(candidate.size)}
        a, b = _features(reference), _features(candidate)
        if abs((reference.width/reference.height)/(candidate.width/candidate.height)-1) > .03:
            raise ValueError('incompatible_geometry')
        perceptual = 1-sum(x != y for x, y in zip(a[0], b[0]))/63
        denominator = sqrt(sum(x*x for x in a[1])*sum(x*x for x in b[1]))
        structure = sum(x*y for x,y in zip(a[1],b[1]))/denominator if denominator else 0
        color = 1-sum(abs(x-y) for ac,bc in zip(a[2],b[2]) for x,y in zip(ac,bc))/(192*3*255)
        components = {'perceptual': perceptual, 'structure': structure, 'color': color}
        exact = sha256(reference_bytes).digest() == sha256(candidate_bytes).digest()
        score = 100 if exact else 100*(.55*perceptual+.35*structure+.10*color)
        return {**result, 'status': 'assessed', 'score': round(score, 2), 'exact_bytes': exact,
                'components': {key: round(value*100, 2) for key,value in components.items()},
                'weights': {'perceptual': .55, 'structure': .35, 'color': .10}}
    except ValueError as exc:
        return {**result, 'reason': str(exc)}
