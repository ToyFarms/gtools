import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
from PIL import Image, ImageDraw
import io
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import World
from gtools.core.growtopia.rttex import RtTexManager
import urllib.parse
from gtools.core.wsl import windows_home
from gtools import setting

manager = RtTexManager()

WORLD_DIR = windows_home() / setting.appdir_name / "worlds"


def render_world(name: str) -> Image.Image:
    path = Path(f"{WORLD_DIR}/{name}")
    w = World.from_net(path.read_bytes())

    img = Image.new("RGBA", (w.width * 32, w.height * 32))

    for idx, tile in enumerate(w.tiles):
        for id in (tile.fg_id, tile.bg_id):
            try:
                if id == 0:
                    continue
                i = item_database.get(id)
                tex = manager.get(windows_home() / f"AppData/Local/Growtopia/game/{i.texture_file.decode()}", i.tex_coord_x * 32, i.tex_coord_y * 32, 32, 32)
                # TODO: rewrite to use render command
                img.paste(tex, (tile.pos.x * 32, tile.pos.y * 32))
                if w.garbage_start != -1 and idx >= w.garbage_start:
                    draw = ImageDraw.Draw(img)
                    draw.rectangle((tile.pos.x * 32, tile.pos.y * 32, tile.pos.x * 32 + 32, tile.pos.y * 32 + 32), outline=(255, 0, 0, 128), width=2)
            except:
                draw = ImageDraw.Draw(img)
                draw.rectangle((tile.pos.x * 32, tile.pos.y * 32, tile.pos.x * 32 + 32, tile.pos.y * 32 + 32), outline=(0, 255, 0, 128), width=2)
        if idx == w.garbage_start:
            draw.rectangle((tile.pos.x * 32, tile.pos.y * 32, tile.pos.x * 32 + 32, tile.pos.y * 32 + 32), outline=(100, 255, 100, 128), width=32)

    return img


class ImageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            if not WORLD_DIR.exists():
                self.wfile.write(f"no world".encode("utf-8"))
                return

            files = sorted(f for f in os.listdir(WORLD_DIR) if os.path.isfile(os.path.join(WORLD_DIR, f)))

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

            self.wfile.write(b"<!DOCTYPE html><html><head>")
            self.wfile.write(b"<title>Available Worlds</title>")
            self.wfile.write(b"</head><body>")
            self.wfile.write(b"<h1>Available Worlds</h1><ul>")

            for filename in files:
                safe_name = html.escape(filename)
                url_name = urllib.parse.quote(filename)
                self.wfile.write(f'<li><a href="/{url_name}">{safe_name}</a></li>'.encode("utf-8"))

            self.wfile.write(b"</ul></body></html>")
            return

        try:
            img = render_world(self.path.removeprefix("/"))
        except:
            return

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(image_bytes)))
        self.end_headers()
        self.wfile.write(image_bytes)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    host = "0.0.0.0"
    port = 8000

    server = HTTPServer((host, port), ImageHandler)
    print(f"Serving image at http://localhost:{port}")
    server.serve_forever()
