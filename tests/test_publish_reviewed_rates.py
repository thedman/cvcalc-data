import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_reviewed_rates as pipeline
from select_reviewed_source import select_source


def source(month='2026-09', name='Convyta', i1=0.04):
    return dict(month_key=month, i1=i1, i2=0.054, source_name=name)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.before = [dict(monthKey='2026-08', i1=0.039, i2=0.053)]

    def test_convyta_happy_path(self):
        self.assertEqual(select_source('2026-09', source(), None)['source_name'], 'Convyta')

    def test_penad_fallback(self):
        self.assertEqual(select_source('2026-09', None, source(name='Penad'))['source_name'], 'Penad')

    def test_both_agree(self):
        self.assertEqual(select_source('2026-09', source(), source(name='Penad'))['corroboration_status'], 'penad_agrees')

    def test_disagree(self):
        with self.assertRaises(Exception):
            select_source('2026-09', source(), source(i1=0.041))

    def test_unavailable(self):
        with self.assertRaises(Exception):
            select_source('2026-09', None, None)

    def test_malformed(self):
        for value in (True, 'bad', None):
            with self.assertRaises(ValueError):
                pipeline.candidate(self.before, '2026-09', source(i1=value))

    def test_unexpected_month(self):
        with self.assertRaises(ValueError):
            pipeline.candidate(self.before, '2026-10', source('2026-10'))

    def test_post_push_exact_verification(self):
        after = pipeline.candidate(self.before, '2026-09', source())
        pipeline.verify(self.before, after, '2026-09', source())
        after[-1]['i1'] = 0.041
        with self.assertRaises(ValueError):
            pipeline.verify(self.before, after, '2026-09', source())

    def exercise(self, latest='2026-08', fail=None, unavailable=None):
        data = [dict(monthKey=latest, i1=0.039, i2=0.053)]
        snapshots = [('head', data)]
        months = []
        def discovery(month, temp):
            months.append(month)
            if unavailable == month:
                raise RuntimeError('no reviewed source found')
            result = source(month)
            snapshots.append(('new', pipeline.candidate(snapshots[-1][1], month, result)))
            return result
        def canonical(temp):
            return snapshots[-1]
        def command(args):
            if fail == 'publication' and args[:2] == ['git', 'push']:
                raise RuntimeError('push rejected')
            return 'head' if args[:2] == ['git', 'rev-parse'] else ''
        def validate(path):
            if fail == 'validator':
                raise RuntimeError('invalid candidate')
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, 'reconcile'), patch.object(pipeline, 'RATES', Path(directory)/'rates.json'), patch.object(pipeline, 'canonical', side_effect=canonical), patch.object(pipeline, 'command', side_effect=command), patch.object(pipeline, 'discover', side_effect=discovery), patch.object(pipeline, 'validate', side_effect=validate), patch.object(pipeline, 'resolve') as resolve, patch.object(pipeline, 'exception') as exception, patch.object(pipeline, 'summary'):
            status = pipeline.run(date(2026, 10, 6), Path(directory))
            return status, months, resolve.call_count, exception.call_args

    def test_already_current(self):
        self.assertEqual(self.exercise(latest='2026-10')[:3], (0, [], 0))

    def test_one_month_backlog(self):
        self.assertEqual(self.exercise(latest='2026-09')[:3], (0, ['2026-10'], 1))

    def test_multi_month_sequential_catchup(self):
        self.assertEqual(self.exercise()[:3], (0, ['2026-09', '2026-10'], 2))

    def test_recovery_then_sourcing_wait(self):
        result = self.exercise(unavailable='2026-10')
        self.assertEqual(result[:3], (1, ['2026-09', '2026-10'], 1))
        self.assertEqual(result[3].args[0], '2026-10')

    def test_failed_publication(self):
        result = self.exercise(fail='publication')
        self.assertEqual(result[:3], (1, ['2026-09'], 0))
        self.assertEqual(result[3].args[1], 'publication')

    def test_validator_failure(self):
        result = self.exercise(fail='validator')
        self.assertEqual(result[:3], (1, ['2026-09'], 0))
        self.assertEqual(result[3].args[1], 'candidate validation')

    def test_adapter_malformed_stops_fallback(self):
        result = type('Result', (), dict(returncode=1, stderr='UNAVAILABLE: malformed Penad table'))()
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'extraction control failure'):
                pipeline.discover('2026-09', Path(directory))

    def test_real_validator_rejects_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'candidate.json'
            path.write_text(json.dumps(pipeline.candidate(self.before, '2026-09', source(i1=0.13))))
            with self.assertRaises(RuntimeError):
                pipeline.validate(path)

    def test_failed_post_push_verification(self):
        after = pipeline.candidate(self.before, '2026-09', source())
        after.append(dict(monthKey='2026-10', i1=0.04, i2=0.054))
        with self.assertRaises(ValueError):
            pipeline.verify(self.before, after, '2026-09', source())

    def test_reconcile_interrupted_issue_closure(self):
        data = pipeline.candidate(self.before, '2026-09', source())
        opened = json.dumps([dict(title='CIA rate update needed: 2026-09')])
        with patch.object(pipeline, 'command', side_effect=[opened, json.dumps(source())]), patch.object(pipeline, 'resolve') as resolve:
            pipeline.reconcile(data)
            resolve.assert_called_once_with('2026-09', source())
        with patch.object(pipeline, 'command', side_effect=[opened, '']), patch.object(pipeline, 'resolve') as resolve:
            with self.assertRaises(RuntimeError):
                pipeline.reconcile(data)
            resolve.assert_not_called()

    def test_issue_deduplication(self):
        body = pipeline.notification('2026-09', 'publication', 'push rejected')
        existing = dict(number=9, state='OPEN')
        with patch.object(pipeline, 'issues', return_value=[existing]), patch.object(pipeline, 'command', return_value=json.dumps(dict(body=body, comments=[]))) as command:
            pipeline.exception('2026-09', 'publication', 'push rejected')
            self.assertEqual(command.call_count, 1)

    def test_issue_create_reopen_close(self):
        with patch.object(pipeline, 'issues', return_value=[]), patch.object(pipeline, 'command') as command:
            pipeline.exception('2026-09', 'publication', 'push rejected')
            self.assertEqual(command.call_args.args[0][:3], ['gh', 'issue', 'create'])
        with patch.object(pipeline, 'issues', return_value=[dict(number=9, state='CLOSED')]), patch.object(pipeline, 'command', return_value=json.dumps(dict(body='', comments=[]))) as command:
            pipeline.exception('2026-09', 'publication', 'push rejected')
            self.assertEqual(command.call_args_list[0].args[0][:3], ['gh', 'issue', 'reopen'])
        with patch.object(pipeline, 'issues', return_value=[dict(number=9, state='OPEN')]), patch.object(pipeline, 'summary'), patch.object(pipeline, 'command') as command:
            pipeline.resolve('2026-09', source())
            self.assertEqual(command.call_args.args[0][:3], ['gh', 'issue', 'close'])


if __name__ == '__main__':
    unittest.main()
