"""Optional ICAO type classification for existing all-aircraft indexes."""
import gzip
import hashlib
import json
from pathlib import Path


def load_classes(path):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    decoded = gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    text = decoded.decode('utf-8')
    data = json.loads(text[text.index('{'):text.rindex('}') + 1])
    result = {}
    for code, value in data.items():
        description = value.get('desc', '') if isinstance(value, dict) else (value[2] if len(value) > 2 else '')
        result[code.upper()] = {'J': 'jet', 'T': 'turbine', 'P': 'piston'}.get(description[-1:], 'unclassified')
    return result, digest


def track_class(track, classes):
    label = str(getattr(track, 'aircraft_class', '') or '').lower()
    mapped = classes.get(str(getattr(track, 'typecode', '') or '').upper(), 'unclassified')
    if 'jet' in (label, mapped):
        return 'jet'
    if label in ('piston', 'turbine') and mapped in ('piston', 'turbine') and label != mapped:
        return 'unclassified'
    return label if label in ('piston', 'turbine') else mapped
