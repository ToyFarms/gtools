import threading
from quart import Quart, request, Response
import httpx
import asyncio
import logging
from hypercorn.config import Config
from hypercorn.asyncio import serve

from gtools.core.growtopia.strkv import StrKV
from gtools.core.network import resolve_doh
from gtools.proxy.event import UpdateServerData
from gtools import setting

app = Quart(__name__)
logger = logging.getLogger("http_proxy")
app.logger.handlers = logger.handlers
app.logger.setLevel(logging.INFO)
logging.getLogger("hpack.hpack").setLevel(logging.WARNING)


@app.route("/growtopia/server_data.php", methods=["POST"])
async def server_data():
    body = await request.get_data()
    headers = dict(request.headers)

    app.logger.info(f"from: {request.remote_addr}")
    app.logger.info(f"\t{request.url=}")
    app.logger.info(f"\t{headers=}")
    app.logger.info(f"\t{body=}")

    upstream_host = resolve_doh(setting.server_data_url)
    upstream_host = upstream_host[0] if upstream_host else setting.server_data_url
    url = f"https://{upstream_host}/growtopia/server_data.php"
    headers["Host"] = setting.server_data_url
    headers["Remote-Addr"] = upstream_host

    async with httpx.AsyncClient(http2=True, verify=False, headers=None) as client:
        resp = await client.post(url, content=body, headers=headers)

    resp_body = resp.content
    kv = StrKV.deserialize(resp_body)
    app.logger.info(f"server_data response: {kv}")

    if "maint" in kv:
        return Response(
            resp_body,
            status=resp.status_code,
            headers=dict(resp.headers),
        )

    orig_server = kv["server", 1].decode()
    orig_port = int(kv["port", 1].decode())

    kv["server", 1] = setting.proxy_server
    kv["port", 1] = setting.proxy_port

    new_body = kv.serialize()

    resp_headers = dict(resp.headers)
    resp_headers["Content-Length"] = str(len(new_body))

    UpdateServerData(server=orig_server, port=orig_port).send()

    return Response(new_body, status=resp.status_code, headers=resp_headers)


class HTTPProxy:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None

    def _make_config(self) -> Config:
        config = Config()
        config.bind = ["0.0.0.0:443"]

        config.certfile = "resources/cert.pem"
        config.keyfile = "resources/key.pem"

        config.alpn_protocols = ["h2", "http/1.1"]

        config.workers = 2
        config.use_reloader = False
        return config

    async def _serve(self):
        assert self._stop_event is not None
        await serve(app, self._make_config(), shutdown_trigger=self._stop_event.wait)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._stop_event = asyncio.Event()
        self._loop.run_until_complete(self._serve())

        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()

        self._loop.run_until_complete(self._loop.shutdown_asyncgens())
        self._loop.close()

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._run_loop,
            name="http-proxy",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        if not self._loop or not self._stop_event:
            return

        self._loop.call_soon_threadsafe(self._stop_event.set)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
            self._thread = None

        self._loop = None
        self._stop_event = None
