from contextlib import closing
from http.server import BaseHTTPRequestHandler
import http.client

import logging
import socket
import socketserver
import ssl
import urllib.parse

from gtools.core.growtopia.strkv import StrKV
from gtools.core.network import resolve_doh
from gtools.proxy.event import UpdateServerData
from gtools import setting


class ProxyHandler(BaseHTTPRequestHandler):
    logger = logging.getLogger("http_proxy")

    def do_POST(self):
        if not self.path.startswith("/growtopia/server_data.php"):
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

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.VerifyMode.CERT_NONE

        ip = resolve_doh(setting.server_data_url)
        ip = ip[0] if ip else setting.server_data_url
        self.logger.debug(f"resolved {setting.server_data_url} to {ip}")

        headers["Host"] = setting.server_data_url
        headers["Remote-Addr"] = ip

        try:
            with closing(http.client.HTTPSConnection(ip, timeout=10, context=context)) as conn:
                conn.request("POST", target_path, body, headers=headers)
                resp = conn.getresponse()
                body = resp.read()
        except socket.timeout:
            self.logger.error("upstream server timed out")
            self.send_response(502)
            return

        headers = {k: v for k, v in resp.headers.items()}
        self.logger.info(f"from {ip} ({setting.server_data_url})")
        self.logger.info(f"\t{self.path=}")
        self.logger.info(f"\t{headers=}")
        self.logger.info(f"\t{body=}")

        kv = StrKV.deserialize(body)
        self.logger.debug(f"server_data.php: {kv}")
        if "maint" in kv:
            self.logger.info("server is in maintenance")

            self.send_response(resp.status)
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

            return

        orig_server = kv["server", 1].decode()
        orig_port = int(kv["port", 1].decode())

        kv["server", 1] = setting.proxy_server
        kv["port", 1] = setting.proxy_port

        body = kv.serialize()
        resp.headers.replace_header("Content-Length", f"{len(body)}")

        UpdateServerData(server=orig_server, port=orig_port).send()

        self.send_response(resp.status)
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def setup_server() -> ThreadedHTTPServer:
    PORT = 443
    logging.debug(f"running http proxy server on :{PORT}")
    httpd = ThreadedHTTPServer(("", PORT), ProxyHandler)

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain("resources/cert.pem", "resources/key.pem")
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    return httpd


if __name__ == "__main__":
    setup_server().serve_forever()
