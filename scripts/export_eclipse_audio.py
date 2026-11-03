#!/usr/bin/env python3
"""Write a point-in-time catalog of real Eclipse Soundscapes scanner outcomes."""
import argparse
import collections
import csv
from datetime import datetime, timezone
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    selection = json.loads((args.root / 'selection.json').read_text())
    review_path = args.root / 'manual-reviews.json'
    reviews = json.loads(review_path.read_text()) if review_path.exists() else {}
    fields = ['site', 'record_url', 'status', 'error', 'audio_path', 'source_filename_timestamp_utc',
              'clip_duration_s', 'source_sha256', 'location_status', 'location_reference',
              'location_uncertainty', 'publisher_clock_setting', 'clock_uncertainty', 'proposal_count', 'proposal_group_count',
              'scanner_interpretation', 'visual_review', 'review_plot']
    rows = []
    for source in selection['sites']:
        site = source['site']
        path = args.root / 'clips' / site / 'result.json'
        result = json.loads(path.read_text()) if path.exists() else {'status': 'not_scanned'}
        review = reviews.get(site, {})
        truth = args.root / 'truth' / (site + '.csv')
        clock_setting = result.get('publisher_clock_setting')
        if truth.exists() and clock_setting is None:
            with truth.open(encoding='utf-8-sig', newline='') as stream:
                clock_setting = next(csv.DictReader(stream), {}).get('WAV Files Time & Date Settings')
        rows.append({'site': site, 'record_url': source['record_url'],
                     'status': result.get('status'), 'error': result.get('error'),
                     'audio_path': result.get('audio_path'),
                     'source_filename_timestamp_utc': result.get('source_filename_timestamp_utc', result.get('clip_start_utc')),
                     'clip_duration_s': result.get('clip_duration_s'),
                     'source_sha256': result.get('recording', {}).get('source_sha256'),
                     'location_status': result.get('location_status'),
                     'location_reference': result.get('location_reference'),
                     'location_uncertainty': result.get('location_uncertainty'),
                     'publisher_clock_setting': clock_setting,
                     'clock_uncertainty': 'filename time is unverified; site-specific clock error is unknown',
                     'proposal_count': result.get('proposal_count'),
                     'proposal_group_count': result.get('proposal_group_count'),
                     'scanner_interpretation': result.get('interpretation'),
                     'visual_review': review.get('visual_review', 'pending'),
                     'review_plot': review.get('plot')})
    directory = args.root / 'reports'
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = directory / ('catalog-' + stamp + '.csv')
    with path.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    counts = collections.Counter(row['status'] for row in rows)
    positives = sum(row['status'] == 'scanned' and (row['proposal_group_count'] or 0) > 0 for row in rows)
    print(json.dumps({'catalog': str(path), 'selected': len(rows), 'statuses': counts,
                      'unreviewed_or_reviewed_proposal_positives': positives,
                      'note': 'proposals are not confirmed aircraft; coordinates stay in separate source files'}))


if __name__ == '__main__':
    main()
