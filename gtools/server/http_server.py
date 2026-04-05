from base64 import b64encode
from http.server import BaseHTTPRequestHandler

import logging
import os
import socketserver
import ssl
import urllib.parse

from gtools.core.growtopia.strkv import StrKV
from gtools import setting


class HTTPHandler(BaseHTTPRequestHandler):
    logger = logging.getLogger("http_handler")

    def do_POST(self) -> None:
        if not self.path.startswith("/growtopia/server_data.php"):
            self.send_response(404)
            self.end_headers()
            return

        parsed = urllib.parse.urlsplit(self.path)
        target_path = parsed.path
        if parsed.query:
            target_path += "?" + parsed.query

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""

        headers = {k: v for k, v in self.headers.items()}
        self.logger.info(f"from: {self.client_address}")
        self.logger.info(f"\t{self.path=}")
        self.logger.info(f"\t{headers=}")
        self.logger.info(f"\t{body=}")

        res = StrKV()

        res.append(["server", setting.server.enet_host])
        res.append(["port", setting.server.enet_port])
        res.append(["loginurl", setting.server.login_url])
        res.append(["type", "1"])
        res.append(["beta_server", setting.server.enet_host])
        res.append(["beta_loginurl", setting.server.login_url])
        res.append(["beta_port", setting.server.enet_port])
        res.append(["beta_type", "1"])
        res.append(["beta2_server", setting.server.enet_host])
        res.append(["beta2_loginurl", setting.server.login_url])
        res.append(["beta2_port", setting.server.enet_port])
        res.append(["beta2_type", "1"])
        res.append(["beta3_server", setting.server.enet_host])
        res.append(["beta3_loginurl", setting.server.login_url])
        res.append(["beta3_port", setting.server.enet_port])
        res.append(["beta3_type", "1"])
        res.append(["type2", "1"])
        res.append(["#maint", "Server is under maintenance. We will be back online shortly. Thank you for your patience!"])
        res.append(["meta", b64encode(os.urandom(32))])
        res.append(["RTENDMARKERBS1001"])

        body = res.serialize()
        self.logger.debug(f"response: {body!r}")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def setup_server() -> ThreadedHTTPServer:
    logging.debug(f"running http server on {setting.server.server_data_host}:{setting.server.server_data_port}")
    httpd = ThreadedHTTPServer((setting.server.server_data_host, setting.server.server_data_port), HTTPHandler)

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain("resources/cert.pem", "resources/key.pem")
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    return httpd


if __name__ == "__main__":
    setup_server().serve_forever()
