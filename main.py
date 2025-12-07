import argparse
import logging
import threading

from gtools.core.utils.network import is_up, resolve_doh
from gtools.proxy import login
from gtools.proxy.proxy import Proxy


def run_proxy() -> None:
    server = login.setup_server()
    t = threading.Thread(target=lambda: server.serve_forever())
    t.start()
    Proxy().run()

    server.shutdown()
    server.server_close()
    t.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("-v", action="store_true")

    subparser = parser.add_subparsers(dest="cmd")
    subparser.add_parser("proxy")
    subparser.add_parser("test")

    args = parser.parse_args()

    if args.v:
        logging.basicConfig(level=logging.DEBUG)

    if args.cmd == "test":
        for host in ("www.growtopia1.com", "www.growtopia2.com"):
            print(f"checking for {host}")

            servers = resolve_doh(host)
            print(f"resolved ip: {servers}")

            should_break = False

            for server in servers:
                up = is_up(server)
                if up:
                    should_break = True
                print(f"{server} status: {'ok' if up else 'unreachable'}")

            if should_break:
                break

            print("checking alternate host")

    elif args.cmd == "proxy":
        run_proxy()
