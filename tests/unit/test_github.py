"""GitHub client error reporting (found in the ES-12 live run)."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from vstd import github


def serve(code, raw):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class ErrorMessageTest(unittest.TestCase):
    def create_pr_error(self, code, raw):
        server = serve(code, raw)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        client = github.Client("Venuvra/fixture", "test-token-not-real", f"http://127.0.0.1:{server.server_port}")
        with self.assertRaises(github.GitHubError) as ctx:
            client.create_pr("standards/update", "main", "t", "b")
        return str(ctx.exception)

    def test_includes_githubs_message(self):
        msg = "GitHub Actions is not permitted to create or approve pull requests."
        err = self.create_pr_error(403, json.dumps({"message": msg}).encode())
        self.assertEqual(err, f"POST /repos/Venuvra/fixture/pulls failed with HTTP 403: {msg}")

    def test_message_is_one_bounded_line(self):
        err = self.create_pr_error(422, json.dumps({"message": "bad\n::error::x" + "y" * 1000}).encode())
        self.assertNotIn("\n", err)
        self.assertIn("bad ::error::x", err)
        self.assertLessEqual(len(err), 400)

    def test_unusable_body_keeps_the_status_code(self):
        for raw in (b"<html>nope</html>", b"[]", json.dumps({"message": 5}).encode(), b""):
            with self.subTest(raw=raw):
                self.assertEqual(self.create_pr_error(500, raw), "POST /repos/Venuvra/fixture/pulls failed with HTTP 500")


if __name__ == "__main__":
    unittest.main()
