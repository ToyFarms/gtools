# gtools

A repository containing most of the reverse engineering effort of the game Growtopia. Also contains some of QOL feature for automating the game.

<p align="center">
  <img src="images/debug_ui.png" width="90%" alt="gtools GUI"/>
</p>

## Quick start

Requirements: [uv](https://docs.astral.sh/uv), Python 3.12 or newer. The DLL hook and the game itself are Windows only. The tooling also runs on Linux and WSL.

Install uv if you do not have it:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh                                        # Linux, macOS
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"     # Windows
```

```sh
git clone --recurse-submodules https://github.com/ToyFarms/gtools
cd gtools

uv python install 3.13
uv venv --python 3.13
source .venv/bin/activate     # Windows: .\.venv\Scripts\activate
uv sync --extra gui           # omit --extra gui for a headless install
```

Already cloned without submodules: `git submodule update --init --recursive`

Run it:

```sh
python main.py --help            # lists command
python main.py proxy             # start the proxy, then launch Growtopia
python -m extension.utils        # in a second terminal: load an extension
python main.py gui               # open the GUI
```

Extensions are separate processes. Start as many as you want, in any order, and stop them with Ctrl+C.

## Features

**Proxy**
- Transparent ENet proxy between client and server
- Live game state: world tiles, dropped items, inventory, local player, ping, connection status
- Automatic world capture, saved to `~/.gtools/worlds`
- Per-account hardware identity spoofing (MAC, hashes, `wk`, `rid`) on login
- Two ways to redirect the client: a DLL hook, or a hosts file entry with a local HTTPS server

**Extensions**
- Out-of-process plugins talking to the proxy through a ZeroMQ broker and protobuf
- Subscribe to packets by type, direction and field filters, with blocking or non-blocking delivery
- Brokers and extensions recover on their own when either side restarts
- Python SDK with command helpers, background threads, packet injection and access to game state

**GUI**
- OpenGL world viewer for tiles, seeds, trees, dropped items, NPCs and players
- Command palette on Ctrl+P
- Proxy panel with connection state, ping and packet activity
- MIDI workspace that converts MIDI files into in-game music notes
- Debug world, dev mode and performance overlay

**Tools**
- Render any captured world to an image
- Simulate world music from a captured world
- Local test server (server data HTTP endpoint and ENet server)
- Items database: parse `items.dat`, fuzzy name search, splice recipes, SQLite export
- Diff `items.dat` versions to see what changed in an update
- Account manager, hosts file manager, persistent settings
- Packet, struct and texture debugging helpers

## Screenshots

<table align="center" width="100%">
  <tr>
    <td align="center" width="50%">
      <p><b>Render to image</b></p>
      <img src="images/render.png" width="100%"/>
    </td>
    <td align="center" width="50%">
      <p><b>MIDI to notes</b></p>
      <img src="images/midi_workspace.png" width="100%"/>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <p><b>Debug world</b></p>
      <img src="images/debug_world.png" width="100%"/>
    </td>
    <td align="center" width="50%">
      <p><b>Debug UI</b></p>
      <img src="images/debug_ui.png" width="100%"/>
    </td>
  </tr>
</table>

## Built-in extensions

Run any of them with `python -m extension.<name>` from the repository root. Commands are typed in the Growtopia chat box. The proxy intercepts them and does not forward them to the server.

### utils

| Command | Description |
| --- | --- |
| `/warp <world>` | Warp by quitting to the main menu first, then joining, with a randomized delay |
| `/nowarp` | Toggle the `/warp` interception |
| `/wset <a> <b>` | Set a pair of worlds |
| `/w` | Switch between the pair set with `/wset` |
| `/exit` | Quit to the main menu |
| `/ping` | Print server and client ping |
| `/fd` | Toggle fast drop |
| `/setdrop [n]` | Set the fast drop amount (default 200) |
| `/item [name or id]` | Total of dropped items in the world, or of one item |
| `/gs` | Growscan style dialog listing every dropped item in the world |
| `/search <name>` | Fuzzy search the items database, prints id and rarity |
| `/find <item>` | Find vending machines selling an item and mark the path to them with particles |

It also dismisses the Growtopia Gazette dialog automatically.

### auto_break

Breaks and rebuilds a set of target tiles in a loop, within punch and build range. It pauses while frozen or while the server is not responding, stops when the character leaves the world or a Magplant runs empty, and logs the cycle rate and an ETA.

| Command | Description |
| --- | --- |
| `/auto` | Start or stop |
| `/id [name or id]` | Set the item to build. Without an argument, the next tile you punch or place sets it |
| `/t bfg` | Target a row in front of you |
| `/t up`, `/t down` | Target a row two tiles above or below you |
| `/t` | Record custom targets by punching or placing, run again to finish |
| `/beep` | Toggle audio alerts |
| `/gaut` | Print the contents and limit of every item sucker in the world |

### auto_empty

Empties an item sucker for you. Wrench the sucker to select it, and the extension retrieves its contents and drops them when the inventory is full. Includes retries, timeouts and resync when a dialog arrives out of order.

| Command | Description |
| --- | --- |
| `/e` | Start or stop |
| `/estatus` | Print the current state, target, item and retry count |

### auto_fish

Reels in and recasts when a fish bites, using randomized delays.

| Command | Description |
| --- | --- |
| `/ft` | Start or stop. Cast once manually to register the bait and position |

### Other extensions

| File | Purpose |
| --- | --- |
| `inspector.py` | `/t` prints the tile data of a punched tile instead of breaking it |
| `analyze_particle.py` | Preview particle effects. `/s <id>`, `/set <id>`, `/alt <n>`, `/c <name>` |
| `analyze_dialog.py` | Builds and sends custom dialogs, useful for testing dialog syntax |
| `fake_world.py` | Sends a saved world file to the client on connect |
| `buy_valen.py` | Repeats a store purchase until it stops succeeding |
| `plant_helper.py` | Disabled. Known to get accounts banned |
| `template.py` | Starting point for your own extension |

`/t` is used by both `auto_break` and `inspector`. Do not run them together.

## Writing an extension

Copy `extension/template.py`. An extension declares an `Interest` that describes which packets it wants, and a handler decorated with `@dispatch`.

```python
class FOO(Extension):
    def __init__(self) -> None:
        super().__init__(name="FOO")

    @dispatch(s.command("/hello", id=s.auto))
    def hello(self, event: PendingPacket) -> PendingPacket | None:
        self.console_log("hello")
        return self.cancel()          # do not forward the command to the server


if __name__ == "__main__":
    FOO().standalone()
```

Handlers can return `self.cancel()` to drop a packet, `self.forward(...)` to replace it, or nothing to pass it through. Delivery modes are `BLOCKING_MODE_BLOCK`, `BLOCKING_MODE_SEND_AND_FORGET` and `BLOCKING_MODE_ONESHOT_AND_CANCEL`. Use `@register_thread` for background loops, `self.push(...)` to inject packets, and `self.state` for the world, inventory and local player. `extension/utils.py` has the most complete examples.

## Command line

```sh
python main.py <command>      # -v for verbose logs
```

| Command | Description |
| --- | --- |
| `proxy` | Run the proxy |
| `gui [-w WORLD] [--dev]` | Open the GUI, optionally with a world file |
| `server` | Run the local test server |
| `test` | Check connectivity to the Growtopia servers |
| `render WORLD [--scale N]` | Render a world file to an image |
| `music WORLD` | Play a world's music blocks |
| `setting list \| get \| set \| reset` | Read and change settings |
| `acc list \| get \| renew \| remove` | Manage spoofed accounts |
| `host enable \| disable \| status \| ensure \| restore` | Manage hosts file entries (backs up the file first, asks for elevation) |
| `world_test` | Parse every saved world and report failures |
| `ext_test`, `stress` | Broker and extension benchmarks |

## Utility scripts

```sh
./s <command>        # Linux, WSL
s.cmd <command>      # Windows
./s --help
```

| Command | Description |
| --- | --- |
| `item <id or name>` | Print an item |
| `search <name> [-n N]` | Fuzzy search items |
| `seed <id>` | Print a seed's info |
| `recipe <id> [-n N]` | Print the splice tree for an item |
| `bake [--path items.dat]` | Generate item constants from `items.dat` |
| `items-to-sql` | Export the items database to SQLite |
| `mine [OLD NEW] [--all] [--consecutive] [--json]` | Diff `items.dat` versions field by field |
| `gap [FILES...]` | Compare `items.dat` versions to locate layout changes |
| `world <name>`, `dropped <name>` | Inspect a saved world or its dropped items |
| `paint <id>`, `tileset <id>`, `render-player` | Render test images |
| `texture <path>` | Convert `.rttex` files to PNG |
| `parse`, `struct-debug`, `analyze` | Decode packets, color a raw struct, summarize logs |
| `klv`, `rid`, `rid-dec` | Generate KLV and RID values, decode a RID timestamp |
| `login-val`, `registry-val` | Check generated login and hardware values against this machine |
| `test`, `clean-test` | Run the test suite with coverage, remove stale snapshots |
| `compile-proto`, `compile-cmod` | Rebuild protobuf bindings and the C modules |

## Configuration

Settings live in `~/.gtools/setting.json`, are reloaded while the program runs, and can be edited with `python main.py setting`. Logs, saved worlds and `accounts.json` are in the same directory.

| Setting | Default | Description |
| --- | --- | --- |
| `server_data_url` | `www.growtopia1.com` | Upstream server data host |
| `proxy_server`, `proxy_port` | `127.0.0.1`, `16999` | Address the client is redirected to |
| `http_server_host`, `http_server_port` | `127.0.0.1`, `443` | Local server data HTTP(S) endpoint |
| `broker_addr` | `tcp://127.0.0.1:6712` | Extension broker address |
| `spoof_hwident` | `true` | Spoof hardware identifiers on login |
| `anomaly_byte_compensation` | `true` | Handle the stray trailing byte. Turn off for private servers |
| `gt_path` | auto detected | Growtopia install directory |
| `heartbeat_interval`, `heartbeat_threshold` | `1.0`, `5.0` | Extension liveness check, in seconds |
| `panic_on_packet_error` | `false` | Raise instead of logging on packet errors |
| `hook.start_delay_ms` | `2500` | Delay before the hook installs |
| `hook.low_power`, `hook.low_power_fps`, `hook.low_power_skip_draws` | `false`, `0`, `false` | Reduce the game's rendering load while botting |
| `hook.stream_game_logs` | `false` | Stream the game's own logs into the proxy |

## How it works

The proxy looks like a server to the client and like a client to the server. The only hard part is getting the client to connect to it.

On startup the client POSTs to `/growtopia/server_data.php` on `www.growtopia1.com`, or `www.growtopia2.com` as a fallback. The response contains the ENet server address. Changing that address redirects the whole session. There are two ways to do it.

**DLL hook (default).** Required from client version 5.59, which added certificate pinning. The injector stubs the function that builds the POST request to capture the version, protocol and platform, then stubs the function that parses the response and rewrites the address to the proxy. Injecting needs elevation. Settings are under `hook.*`.

**Hosts file.** Point both hostnames at `127.0.0.1` with `python main.py host enable`, and the local HTTPS server (self-signed certificate in `resources/`) answers the request with the proxy address. This only works on clients without certificate pinning.

From there the proxy forwards ENet traffic in both directions, parsing every packet into state and handing copies to extensions through the broker.

## Development

```sh
./s test                  # tests with coverage, add -r to serve the HTML report
pytest --forked -vv       # tests only
UPDATE=1 ./s test         # re-record snapshot outputs
./s compile-proto         # needs protoc
./s compile-cmod -j 4     # needs a C compiler, -B forces a rebuild
```

Prebuilt binaries for the C modules and the hook are included in the repository.

## Protocol notes

Reverse engineering notes live in `docs/`: server data and ENet setup, packet layouts, variant and string key-value types, login payload, registry values, and dialog syntax.

## Legal and ethics

Using a proxy breaks Growtopia's rules and can get your account banned. You use this software at your own risk.

Most players rely on some form of outside help, and this project takes the position that a proxy is acceptable when it automates repetitive actions for a single player. It is not meant for multi-account botting or anything built to damage the game economy.

Love.