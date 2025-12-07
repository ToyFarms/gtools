from http.server import BaseHTTPRequestHandler
import http.client

import socketserver
import ssl

from gtools.core.growtopia.strkv import StrKV
from gtools.core.utils.network import resolve_doh
from gtools.proxy.event import UpdateServerData
from gtools.proxy.setting import _setting


class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        print("GET")

    def do_POST(self):
        if self.path != "/growtopia/server_data.php":
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        headers = {k: v for k, v in self.headers.items()}
        print(headers)
        print(body)

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.VerifyMode.CERT_NONE

        conn = http.client.HTTPSConnection(
            resolve_doh(_setting.server_data_url)[0], context=context
        )
        conn.request("POST", "/growtopia/server_data.php", body, headers)

        resp = conn.getresponse()
        body = resp.read()
        kv = StrKV.deserialize(body)

        orig_server = kv["server", 1].decode()
        orig_port = int(kv["port", 1].decode())

        kv["server", 1] = _setting.proxy_server
        kv["port", 1] = _setting.proxy_port
        kv["type2", 1] = 1

        body = kv.serialize()
        resp.headers.replace_header("Content-Length", f"{len(body)}")

        self.send_response(resp.status)
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

        UpdateServerData(server=orig_server, port=orig_port).send()


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


def run_server() -> None:
    httpd = ThreadedHTTPServer(("", 443), ProxyHandler)

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain("resources/cert.pem", "resources/key.pem")
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    run_server()
