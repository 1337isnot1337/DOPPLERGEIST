#!/usr/bin/env python3
"""Collect chronological public Eclipse Soundscapes clips and scan audio only.

The source list and clip offsets are chosen before listening or scanner results.
Publisher location metadata is stored separately and is never used by discovery.
"""
import argparse
from contextlib import ExitStack
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone

import requests
from remotezip import RemoteZip
from dopplergeist.discovery import discover_events
from dopplergeist.intake import intake_recording


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    tmp.replace(path)


def choose(root, limit, excluded):
    path = root / 'selection.json'
    if path.exists():
        return json.loads(path.read_text())
    selected = []
    for page in range(1, 26):
        response = requests.get('https://zenodo.org/api/records', params={
            'q': '"Eclipse Soundscapes" "ESID"', 'size': 25,
            'page': page, 'sort': 'mostrecent'}, timeout=90)
        response.raise_for_status()
        for record in response.json()['hits']['hits']:
            title = record.get('metadata', {}).get('title', '')
            match = re.search(r'2024-04-08 .* Eclipse ESID#\s*(\d+)', title)
            if not match:
                continue
            site = match.group(1).zfill(3)
            if site in excluded or any(x['site'] == site for x in selected):
                continue
            zipname = f'ESID_{site}_2024_04_08.zip'
            files = {f['key']: f for f in record.get('files', [])}
            if zipname not in files or 'file_list.csv' not in files or 'total_eclipse_data.csv' not in files:
                continue
            # Keep raw publisher metadata, which may contain the coordinates,
            # outside the per-clip scanner directory and input arguments.
            save(root / 'truth' / f'{site}.json', record)
            selected.append({'site': site, 'record_id': record['id'], 'title': title,
                             'record_url': f"https://zenodo.org/records/{record['id']}",
                             'zip_name': zipname,
                             'zip_url': files[zipname]['links']['self'],
                             'catalog_url': files['file_list.csv']['links']['self'],
                             'location_url': files['total_eclipse_data.csv']['links']['self']})
            if len(selected) >= limit:
                break
        if len(selected) >= limit or not response.json()['hits']['hits']:
            break
    data = {'selection': 'first eligible distinct sites in Zenodo mostrecent search order; '
                         'first 600 continuous seconds of UTC-named WAV files on 2024-04-08, '
                         'selected before audio or scanner results',
            'excluded_sites': sorted(excluded), 'sites': selected}
    save(path, data)
    return data


def get(url):
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    return response.content


def scan(root, item):
    site = item['site']
    folder = root / 'clips' / site
    folder.mkdir(parents=True, exist_ok=True)
    result_path = folder / 'result.json'
    if result_path.exists():
        return json.loads(result_path.read_text())
    result = {'source': item, 'status': 'failed', 'stage': 'acquisition',
              'location_reference': str(root / 'truth' / (site + '.csv')),
              'location_uncertainty': 'publisher-provided; per-site coordinate accuracy not independently established',
              'clock_uncertainty': 'filename timestamp is a publisher claim; site-specific clock setting and error must be checked',
              'interpretation': 'unreviewed moving-tone proposals; aircraft identity not established'}
    started = time.monotonic()
    try:
        location = get(item['location_url'])
        (root / 'truth' / (site + '.csv')).write_bytes(location)
        location_rows = list(csv.DictReader(io.StringIO(location.decode('utf-8-sig'))))
        result['publisher_clock_setting'] = (location_rows[0].get('WAV Files Time & Date Settings')
                                             if location_rows else None)
        try:
            latitude = float(location_rows[0]['Latitude'])
            longitude = float(location_rows[0]['Longitude'])
            location_known = math.isfinite(latitude) and math.isfinite(longitude) and abs(latitude) <= 90 and abs(longitude) <= 180
        except (IndexError, KeyError, TypeError, ValueError):
            location_known = False
        result['location_status'] = 'publisher_coordinates_present' if location_known else 'unavailable'
        catalog = list(csv.DictReader(io.StringIO(get(item['catalog_url']).decode('utf-8-sig'))))
        hashes = {r['File Name']: r['SHA-512 Hash'].lower() for r in catalog
                  if item['zip_name'] in r.get('Notes', '')}
        with RemoteZip(item['zip_url'], timeout=90) as archive:
            names = sorted(n for n in archive.namelist() if re.search(r'20240408_\d{6}\.wav$', n, re.I))
            if not names:
                raise ValueError('no timestamped WAV members')
            wavpath = folder / 'source-concatenated.wav'
            members, format_params = [], None
            start_time = None
            written = 0
            with ExitStack() as stack:
                output = None
                for name in names:
                    timestamp = datetime.strptime(Path(name).stem, '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
                    if start_time is None:
                        start_time = timestamp
                    elif (timestamp - start_time).total_seconds() != written:
                        raise ValueError(f'WAV timestamps are not continuous: {name}')
                    with archive.open(name) as source, wave.open(source, 'rb') as audio:
                        fmt = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate())
                        frames = audio.getnframes()
                        if format_params is not None and fmt != format_params:
                            raise ValueError(f'WAV format changed: {name}')
                        if format_params is None:
                            output = stack.enter_context(wave.open(str(wavpath), 'wb'))
                            output.setnchannels(fmt[0]); output.setsampwidth(fmt[1]); output.setframerate(fmt[2])
                            format_params = fmt
                        used = min(frames, (600 - written) * fmt[2])
                        if used <= 0 or used % fmt[2]:
                            raise ValueError(f'WAV duration is not a whole number of seconds: {name}')
                        pcm = audio.readframes(used)
                        if len(pcm) != used * fmt[0] * fmt[1]:
                            raise ValueError(f'truncated WAV PCM: {name}')
                        output.writeframesraw(pcm)
                        written += used // fmt[2]
                    members.append({'name': name, 'publisher_full_file_sha512': hashes.get(Path(name).name),
                                    'publisher_full_file_hash_verified': False,
                                    'pcm_prefix_sha256': hashlib.sha256(pcm).hexdigest(),
                                    'frames_used': used, 'total_frames': frames})
                    if written == 600:
                        break
                if written != 600:
                    raise ValueError('less than 600 seconds of continuous WAV audio')
        mp3 = folder / 'input.mp3'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(wavpath),
                        '-vn', '-codec:a', 'libmp3lame', '-q:a', '4', str(mp3)], check=True, timeout=120)
        wavpath.unlink()
        result.update(stage='scan', source_members=members,
                      source_filename_timestamp_utc=start_time.isoformat(), clip_duration_s=600,
                      audio_path=str(mp3), source_format={'channels': format_params[0],
                      'sample_width_bytes': format_params[1], 'sample_rate_hz': format_params[2]})
        recording = intake_recording(mp3, folder / 'intake')
        events = discover_events(recording)
        result.update(status='scanned', stage='complete', recording=recording.metadata, events=events,
                      proposal_count=len(events),
                      proposal_group_count=len({e.get('harmonic_group_id') or e['event_id'] for e in events}),
                      aircraft_doppler_verified=None)
        recording.samples_path.unlink()
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
    result['elapsed_s'] = round(time.monotonic() - started, 3)
    save(result_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--sites', type=int, default=50)
    parser.add_argument('--exclude-selection', action='append', type=Path, default=[])
    parser.add_argument('--exclude-site', action='append', default=[])
    args = parser.parse_args()
    if args.sites <= 0:
        parser.error('--sites must be positive')
    excluded = {site.zfill(3) for site in args.exclude_site}
    for path in args.exclude_selection:
        excluded.update(site['site'] for site in json.loads(path.read_text())['sites'])
    args.root.mkdir(parents=True, exist_ok=True)
    sites = choose(args.root, args.sites, excluded)['sites']
    counts = {'scanned': 0, 'failed': 0, 'proposal_positive': 0, 'no_proposals': 0}
    for index, item in enumerate(sites, 1):
        result = scan(args.root, item)
        counts[result['status']] += 1
        if result['status'] == 'scanned':
            counts['proposal_positive' if result['proposal_count'] else 'no_proposals'] += 1
        print(f"{index}/{len(sites)} site={item['site']} status={result['status']} "
              f"groups={result.get('proposal_group_count', '-')} counts={counts}", flush=True)
        save(args.root / 'progress.json', {'completed': index, 'selected': len(sites), **counts})
    return 0


if __name__ == '__main__':
    sys.exit(main())
