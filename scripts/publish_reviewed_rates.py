#!/usr/bin/env python3
"""Fail-closed, sequential reviewed-rate publication transaction."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import date

from check_new_month import expected_latest
from fetch_convyta_rates import next_month
from select_reviewed_source import select_source

ROOT = Path(__file__).resolve().parents[1]
RATES = ROOT / 'cia_rates.json'


def command(args):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'{args[0]} failed')
    return result.stdout


def validate(path):
    command([sys.executable, 'scripts/validate_rates.py', str(path)])


def candidate(data, month, source):
    if month != next_month(data[-1]['monthKey']) or source['month_key'] != month:
        raise ValueError('source month must equal next canonical month')
    row = {'monthKey': month}
    for field in ('i1', 'i2'):
        value = source[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'{field} must be numeric')
        row[field] = value
    return data + [row]


def verify(before, after, month, source):
    expected = candidate(before, month, source)
    if after != expected:
        raise ValueError('canonical main differs from exact validated one-month candidate')


def summary(message):
    print(message)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(message + '\n\n')


def issue_title(month):
    return f'CIA rate update needed: {month}'


def notification(month, stage, detail):
    # Dates/run IDs deliberately excluded: repeated identical failures deduplicate.
    fingerprint = hashlib.sha256(f'{month}:{stage}:{detail}'.encode()).hexdigest()[:16]
    return f'<!-- cia-production-exception {fingerprint} -->\nHUMAN ACTION REQUIRED\nExpected month: {month}\nFailure stage: {stage}\n{detail}\nNo estimates or skipped months are permitted.'


def issues(month):
    results = json.loads(command(['gh', 'issue', 'list', '--state', 'all', '--search', f'{issue_title(month)} in:title', '--limit', '100', '--json', 'number,title,state']))
    return [item for item in results if item['title'] == issue_title(month)]


def exception(month, stage, detail):
    body = notification(month, stage, detail)
    matches = issues(month)
    if not matches:
        command(['gh', 'issue', 'create', '--title', issue_title(month), '--body', body])
        return
    issue = next((item for item in matches if item['state'] == 'OPEN'), matches[0])
    number = str(issue['number'])
    if issue['state'] != 'OPEN':
        command(['gh', 'issue', 'reopen', number])
    existing = json.loads(command(['gh', 'issue', 'view', number, '--json', 'body,comments']))
    marker = body.splitlines()[0]
    if marker not in existing['body'] and not any(marker in comment['body'] for comment in existing['comments']):
        command(['gh', 'issue', 'comment', number, '--body', body])


def resolve(month, source):
    provenance = json.dumps(source, sort_keys=True)
    message = f'Post-push canonical verification passed for {month}.\nReviewed source provenance:\n```json\n{provenance}\n```'
    summary(message)
    for issue in issues(month):
        if issue['state'] == 'OPEN':
            command(['gh', 'issue', 'close', str(issue['number']), '--comment', message])


def discover(month, temp):
    sources = []
    errors = []
    for name in ('convyta', 'penad'):
        output = temp / f'{name}-{month}.json'
        output.unlink(missing_ok=True)
        args = [sys.executable, f'scripts/fetch_{name}_rates.py', '--month', month, '--rates-file', str(RATES), '--json-out', str(output)]
        result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
        if result.returncode:
            detail = result.stderr.strip()
            if any(marker in detail.lower() for marker in ('conflicting', 'non-numeric', 'malformed', 'unapproved', 'outside hard', 'not expected next')):
                raise RuntimeError(f'{name} extraction control failure: {detail}')
            sources.append(None)
            errors.append(f'{name}: {detail}')
        else:
            # A malformed successful extraction is a control exception, not fallback.
            sources.append(json.loads(output.read_text(encoding='utf-8')))
    try:
        return select_source(month, *sources)
    except Exception as exc:
        raise RuntimeError(f'{exc}; ' + '; '.join(errors)) from exc


def canonical(temp):
    command(['git', 'fetch', 'origin', 'main'])
    revision = command(['git', 'rev-parse', 'origin/main']).strip()
    path = temp / 'canonical.json'
    path.write_text(command(['git', 'show', f'{revision}:cia_rates.json']), encoding='utf-8')
    validate(path)
    return revision, json.loads(path.read_text(encoding='utf-8'))


class ReconciliationError(RuntimeError):
    def __init__(self, month, detail):
        super().__init__(detail)
        self.month = month


def reconcile(data):
    """Recover issue closure after a push succeeded but the runner failed later."""
    opened = json.loads(command(['gh', 'issue', 'list', '--state', 'open', '--limit', '100', '--search', '"CIA rate update needed:" in:title', '--json', 'title']))
    rows = {row['monthKey']: row for row in data}
    pending = [item['title'].removeprefix('CIA rate update needed: ') for item in opened]
    pending = [month for month in pending if month in rows]
    if not pending:
        return
    history = command(['git', 'log', 'origin/main', '--format=%B', '--', 'cia_rates.json'])
    for month in pending:
        evidence = None
        for line in history.splitlines():
            if not line.startswith('{'):
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get('month_key') == month:
                evidence = item
                break
        if evidence is None:
            raise ReconciliationError(month, f'Unresolved canonical issue for {month} has no automated publication provenance; human reconciliation required')
        if any(rows[month][field] != evidence[field] for field in ('i1', 'i2')):
            raise ReconciliationError(month, f'Canonical {month} differs from publication provenance')
        resolve(month, evidence)


def run(today, temp):
    month = expected_latest(today)
    stage = 'canonical read/validation'
    try:
        revision, data = canonical(temp)
        # Do not publish using scripts from a stale checkout.
        if command(['git', 'rev-parse', 'HEAD']).strip() != revision:
            raise RuntimeError('checkout is not current origin/main; rerun on main')
        stage = 'prior publication issue reconciliation'
        reconcile(data)
        target = expected_latest(today)
        if data[-1]['monthKey'] >= target:
            summary(f'Canonical already current: {data[-1]["monthKey"]}; calendar target {target}.')
            return 0
        while data[-1]['monthKey'] < target:
            month = next_month(data[-1]['monthKey'])
            stage = 'reviewed extraction/source selection'
            source = discover(month, temp)
            stage = 'candidate validation'
            updated = candidate(data, month, source)
            RATES.write_text(json.dumps(updated, indent=2) + '\n', encoding='utf-8')
            validate(RATES)
            stage = 'publication'
            command(['git', 'config', 'user.name', 'github-actions[bot]'])
            command(['git', 'config', 'user.email', 'github-actions[bot]@users.noreply.github.com'])
            command(['git', 'add', '--', 'cia_rates.json'])
            command(['git', 'commit', '-m', f'Publish {month} validated reviewed CIA rates', '-m', json.dumps(source, sort_keys=True)])
            # Ordinary fast-forward push; concurrent updates fail closed, never force.
            command(['git', 'push', 'origin', 'HEAD:refs/heads/main'])
            stage = 'post-push canonical verification'
            revision, after = canonical(temp)
            verify(data, after, month, source)
            stage = 'issue resolution'
            resolve(month, source)
            data = after
        summary(f'Production verified through {data[-1]["monthKey"]}.')
        return 0
    except Exception as exc:
        month = getattr(exc, 'month', month)
        summary(f'HUMAN ACTION REQUIRED — expected month {month}; failure stage {stage}: {exc}')
        try:
            exception(month, stage, str(exc))
        except Exception as issue_error:
            summary(f'Exception issue update also failed: {issue_error}')
        return 1


if __name__ == '__main__':
    temp = Path(os.environ.get('RUNNER_TEMP', ROOT / '.pipeline-temp'))
    temp.mkdir(parents=True, exist_ok=True)
    sys.exit(run(date.today(), temp))
