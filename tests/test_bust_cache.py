"""Exercise the cache workflow's actual request code without external calls."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import textwrap
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/bust-cache.yml'
SCRIPT = textwrap.dedent(WORKFLOW.read_text().split("python3 - <<'PY'\n", 1)[1]).rsplit('\nPY', 1)[0]


class BustCacheTests(unittest.TestCase):
    def run_refresh(self, payload=None, error=None, credentials=True, raw_body=None):
        body = raw_body if raw_body is not None else json.dumps(payload if payload is not None else {'url': 'ok'}).encode()
        output = io.StringIO()
        environment = {'FB_APP_ID': 'test-app', 'FB_APP_SECRET': 'test-secret' if credentials else ''}
        with patch.dict('os.environ', environment), redirect_stdout(output), \
                patch('urllib.request.urlopen', side_effect=error or (lambda *a, **kw: io.BytesIO(body))) as call:
            try:
                exec(compile(SCRIPT, str(WORKFLOW), 'exec'), {})
                failure = None
            except SystemExit as failure_result:
                failure = str(failure_result)
        diagnostic = output.getvalue() + (failure or '')
        self.assertNotIn('test-app', diagnostic)
        self.assertNotIn('test-secret', diagnostic)
        return call, output.getvalue(), failure

    def test_refreshes_only_canonical_domain_with_bounded_post_requests(self):
        call, output, failure = self.run_refresh()
        self.assertIsNone(failure)
        urls = []
        for args, kwargs in call.call_args_list:
            request = args[0]
            self.assertEqual(request.full_url, 'https://graph.facebook.com/')
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(kwargs['timeout'], 30)
            body = parse_qs(request.data.decode())
            self.assertEqual(body['access_token'], ['test-app|test-secret'])
            self.assertEqual(body['scrape'], ['true'])
            urls.extend(body['id'])
        self.assertEqual(urls, ['https://usvschina.ai', 'https://usvschina.ai/',
                                'https://usvschina.ai/index.html', 'https://usvschina.ai/og-image.png'])
        self.assertIn('Facebook OG cache refreshed', output)

    def test_api_error_stops_refresh_and_never_claims_success(self):
        call, output, failure = self.run_refresh({'error': {'message': 'test-secret'}})
        self.assertIn('API rejected request', failure)
        self.assertEqual(call.call_count, 1)
        self.assertNotIn('Facebook OG cache refreshed', output)

    def test_http_error_is_sanitized_and_fails(self):
        _, _, failure = self.run_refresh(error=HTTPError('test-secret', 403, 'test-app', {}, None))
        self.assertIn('HTTP 403', failure)

    def test_transport_errors_are_sanitized_and_fail(self):
        for error in (URLError('test-secret'), TimeoutError('test-secret')):
            with self.subTest(error=type(error).__name__):
                _, _, failure = self.run_refresh(error=error)
                self.assertIn('request or response error', failure)

    def test_malformed_json_fails(self):
        _, _, failure = self.run_refresh(raw_body=b'<html>test-secret</html>')
        self.assertIn('request or response error', failure)

    def test_missing_credentials_fail_without_requests(self):
        call, _, failure = self.run_refresh(credentials=False)
        self.assertIn('credentials not configured', failure)
        call.assert_not_called()

    def test_unexpected_or_explicitly_unsuccessful_response_fails(self):
        for payload in ([], {'success': False}):
            with self.subTest(payload=payload):
                _, _, failure = self.run_refresh(payload)
                self.assertIn('API rejected request', failure)

    def test_workflow_does_not_suppress_failure(self):
        self.assertNotIn('continue-on-error:', WORKFLOW.read_text())


if __name__ == '__main__':
    unittest.main()
