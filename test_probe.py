import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from probe import inspect_log, normalize, request_check


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, data):
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/redirect/models":
            self.send_response(302)
            self.send_header("Location", "/v1/models")
            self.end_headers()
        elif self.headers.get("Authorization") != "Bearer test-token":
            self.send_error(401)
        else:
            self.respond({"data": [{"id": "example-model"}]})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        body = json.loads(raw)
        if self.path == "/v1/responses" and body.get("store") is False:
            self.respond({"object": "response", "status": "completed", "output": []})
        else:
            self.send_error(400)


class ProbeTest(unittest.TestCase):
    def test_route_and_log(self):
        with self.assertRaises(ValueError):
            normalize("https://api.openai.com/v1", "relay")
        with self.assertRaises(ValueError):
            normalize("https://example.com/v1", "official")
        self.assertEqual(normalize("https://example.com", "relay"), "https://example.com/v1")
        report = inspect_log("401 https://api.openai.com/v1/responses sk-secret", "relay")
        self.assertIn("混用", report.title)
        self.assertNotIn("secret", report.details)

    def test_requests(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), Gateway) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                self.assertIn("找到了", request_check(url, "relay", "test-token", "example-model", "models").details)
                self.assertIn("通过", request_check(url, "relay", "test-token", "example-model", "responses").details)
                self.assertIn("401", request_check(url, "relay", "wrong", "", "models").title)
                self.assertIn("302", request_check(url + "/redirect", "relay", "test-token", "", "models").title)
            finally:
                server.shutdown()
                worker.join()


if __name__ == "__main__":
    unittest.main()
