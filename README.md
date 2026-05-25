# UAV MCP

MCP server for controlling ArduPilot-compatible UAVs (QuadCopters). `uav_mcp` is a thin **MCP-to-HTTP shim** that exposes drone command, movement, and telemetry as MCP tools and delegates all vehicle logic to a [`uav_api`](https://github.com/Project-GrADyS/uav_api) HTTP server. Powered by the [official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk), served over Streamable HTTP at `/mcp`. Supports real drones via MAVLink and simulated drones via ArduPilot SITL.

**Features:**
- **MCP tool interface** at `/mcp` — connect any MCP client (Claude Desktop, Claude Code, LangGraph, custom agents) to control drones
- Full flight control: arm and takeoff in a single command
- GPS and NED movement commands (fire-and-forget and blocking variants)
- Rich telemetry: GPS, NED position, compass, battery, sensor health
- Two run modes: **embedded** (spawns its own `uav-api`) or **external** (points at a running `uav-api`)
- Gradys Ground Station integration and Mission Planner streaming are pass-throughs to `uav-api`

---

# Architecture

```
MCP client  ──HTTP /mcp──►  uav-mcp  ──HTTP──►  uav-api  ──MAVLink──►  Vehicle / SITL
```

- `uav-mcp` owns only the MCP transport. Each tool is an `async` function that issues one (or two, for `arm_and_takeoff`) HTTP calls against `uav-api` and returns the response JSON to the MCP client.
- `uav-api` owns the MAVLink connection, the drain loop, SITL spawning, the Gradys GS push, and script execution.
- In **embedded mode** (the default), `uav-mcp` spawns `uav-api` as a subprocess on a private port (default `8001`) and tears it down on shutdown.
- In **external mode** (`--uav_api_url`), `uav-mcp` connects to a separately-running `uav-api` and does not spawn or kill it.

---

# Installation

## Prerequisites

- Python 3.10+
- [`uav-api`](https://github.com/Project-GrADyS/uav_api) installed and on `PATH` (pulled in as a dependency)
- For simulated flights: ArduPilot repository built locally, and `xterm` installed.
  - Clone and build ArduPilot: https://ardupilot.org/dev/docs/where-to-get-the-code.html
  - SITL setup guide: https://ardupilot.org/dev/docs/SITL-setup-landingpage.html

## Installing from PyPI (recommended)

```bash
pip install uav-mcp
```

Restart your terminal after installation.

## Installing from source (development)

```bash
git clone https://github.com/Project-GrADyS/uav_mcp
cd uav_mcp
pip install -e .
```

Restart your terminal after installation.

---

# Getting Started

## Embedded mode (default) — real drone

`uav-mcp` spawns `uav-api` internally on port `8001` and connects to your vehicle via MAVLink:

```bash
uav-mcp --port 8000 --uav_connection 127.0.0.1:17171 --connection_type udpin --sysid 1
```

The `--connection_type` controls the UDP direction (passed through to `uav-api`):
- `udpin` — server listens, drone connects to it (most common)
- `udpout` — server connects out to the drone
- `usb` — serial connection (set `--uav_connection` to the serial device path, e.g. `/dev/ttyUSB0`)

## Embedded mode — simulation (SITL)

`uav-mcp` spawns `uav-api`, which in turn spawns ArduCopter SITL in a new `xterm` window:

```bash
uav-mcp --simulated true --ardupilot_path ~/ardupilot --speedup 1 --port 8000 --sysid 1
```

SITL binds to the address in `--uav_connection` (default `127.0.0.1:17171`). The `--speedup` factor controls simulation speed (e.g. `5` = 5x real time). `--location` sets the SITL home position (default `AbraDF`).

## External mode — point at a running uav-api

Useful for multi-MCP setups, debugging, or sharing one `uav-api` across clients. Run `uav-api` yourself:

```bash
uav-api --simulated true --ardupilot_path ~/ardupilot --port 9000 --sysid 1
```

Then point `uav-mcp` at it:

```bash
uav-mcp --port 8000 --uav_api_url http://localhost:9000 --sysid 1
```

In external mode, `uav-mcp` does **not** spawn or kill `uav-api`, and ignores all pass-through args except `--sysid` (used to tag responses).

## Using a configuration file

All arguments can be provided via an INI file:

```ini
[api]
port=8000
uav_connection=127.0.0.1:17171
connection_type=udpin
sysid=1

[simulated]
ardupilot_path=~/ardupilot
location=AbraDF
gs_connection=[]
speedup=1

[logs]
log_console=[]
log_path=None
debug=[]
script_logs=None
```

Run with:

```bash
uav-mcp --config /path/to/config.ini
```

CLI arguments always override values from the config file.

---

# Startup and Shutdown Lifecycle

**Startup** (`uav_mcp/run_mcp.py`):
1. CLI arguments are parsed and serialized into the `UAV_ARGS` env var.
2. If `--uav_api_url` is not set: `uav-api` is spawned as a subprocess tagged with `UAV_MCP_API_TAG=MCP_API_<sysid>` for later teardown. `uav-api` then handles SITL spawn, MAVLink connection, drain loop, and (if `--gradys_gs` is set) the GS push.
3. `wait_for_uav_api(...)` polls `http://<host>:<port>/docs` until ready (timeout 120s).
4. The shared `aiohttp.ClientSession` in `uav_api_client` is initialized.
5. The MCP server starts listening on `--port` (`mcp.run_streamable_http_async()`).

**Shutdown** (on Ctrl+C or SIGTERM):
1. The MCP server stops accepting requests.
2. The `aiohttp` session is closed.
3. If `uav-api` was spawned: `kill_uav_api_by_tag` scans `psutil.process_iter` for processes whose environment carries `UAV_MCP_API_TAG=MCP_API_<sysid>` and kills them — this brings down both `uav-api` and any SITL processes it spawned.

---

# Verifying the MCP Server

Once the server is running, you can verify it by connecting an LLM agent.

## Using Claude Desktop

Add the MCP server to your Claude Desktop configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "uav-1": { "url": "http://localhost:8000/mcp" }
  }
}
```

Restart Claude Desktop, then ask:

> "Get the drone's general telemetry"

Claude will call the `get_general_telemetry` tool and return airspeed, groundspeed, heading, throttle, and altitude — confirming the MCP server is connected to the vehicle.

## Using Claude Code

Create an `.mcp.json` file in your project directory:

```json
{
  "mcpServers": {
    "uav-1": { "url": "http://localhost:8000/mcp" }
  }
}
```

Then start Claude Code and ask it to interact with the drone:

> "Arm the drone and take off to 20 meters"

Claude Code will call `arm_and_takeoff` with `alt=20`.

## Multi-drone setup

Run one MCP server per drone, each spawning its own `uav-api` on a distinct internal port:

```bash
uav-mcp --simulated true --ardupilot_path ~/ardupilot --port 8001 --uav_api_port 9001 --sysid 1
uav-mcp --simulated true --ardupilot_path ~/ardupilot --port 8002 --uav_api_port 9002 --sysid 2
```

Configure the MCP client with both servers:

```json
{
  "mcpServers": {
    "uav-1": { "url": "http://localhost:8001/mcp" },
    "uav-2": { "url": "http://localhost:8002/mcp" }
  }
}
```

The LLM agent can then control multiple drones by calling tools on each server.

---

# MCP Tools

Tools are organized in three groups:

**Command:** `arm_and_takeoff` — arms the vehicle, switches to GUIDED mode, and takes off to a specified altitude.

**Movement:** `go_to_gps`, `go_to_gps_wait`, `go_to_ned`, `go_to_ned_wait`, `drive`, `drive_wait`, `stop`, `resume` — GPS and NED navigation with fire-and-forget and blocking variants.

**Telemetry:** `get_general_telemetry`, `get_gps`, `get_ned`, `get_compass`, `get_sys_status`, `get_sensor_status`, `get_battery`, `get_home` — read vehicle state and sensor data.

Each tool issues a single HTTP call to the matching `uav-api` endpoint (`arm_and_takeoff` issues two: `/command/arm` then `/command/takeoff`) and returns the response JSON verbatim. On HTTP error, the tool returns `{"device":"uav","id":"<sysid>","error":"<TOOL> FAIL: <detail>"}`.

See `.claude/docs/specification.md` for full parameter and response details.

---

# CLI Arguments Reference

Run `uav-mcp --help` for a quick reference.

## uav_mcp-owned arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--config` | None | Path to INI config file (`[api]`, `[simulated]`, `[logs]` sections) |
| `--port` | 8000 | Port the MCP server listens on (Streamable HTTP) |
| `--uav_api_url` | None | URL of an already-running `uav-api`. When set, `uav-mcp` connects to it and does not spawn its own. |
| `--uav_api_port` | 8001 | Port the spawned `uav-api` subprocess listens on. Ignored when `--uav_api_url` is set. |

## Passed through to `uav-api`

These are forwarded verbatim to the spawned `uav-api` subprocess (and ignored in external mode, except `--sysid`).

| Argument | Default | Description |
|----------|---------|-------------|
| `--sysid` | 10 | MAVLink system ID; must match the drone's `SYSID_THISMAV` parameter |
| `--uav_connection` | `127.0.0.1:17171` | MAVLink address — `host:port` for UDP, or serial device path for USB |
| `--connection_type` | `udpin` | `udpin` — server listens; `udpout` — server connects out; `usb` — serial |
| `--gradys_gs` | None | `host:port` of Gradys Ground Station — `uav-api` pushes GPS location every second |
| `--scripts_path` | `~/uav_scripts` | Directory where mission scripts are saved |
| `--python_path` | `python3` | Python binary used to run scripts |
| `--simulated` | `false` | Set to `true` to spawn ArduCopter SITL alongside `uav-api` |
| `--ardupilot_path` | `~/ardupilot` | Path to local ArduPilot repository (simulated mode) |
| `--location` | `AbraDF` | Named home position for SITL |
| `--speedup` | 1 | SITL simulation time multiplier |
| `--gs_connection` | `[]` | Extra `host:port` addresses SITL streams telemetry to (e.g. Mission Planner) |
| `--log_console` | `[]` | Components to print logs to console: `API`, `COPTER`, `GRADYS_GS` |
| `--log_path` | None | File path to write all component logs combined |
| `--debug` | `[]` | Same component names as `--log_console` but at DEBUG verbosity |
| `--script_logs` | None | Directory where script stdout/stderr are saved as timestamped `.log` files |

See the [`uav-api` documentation](https://github.com/Project-GrADyS/uav_api) for endpoint-level details.

---

# Extra Features

## Gradys Ground Station Integration

Set `--gradys_gs <host:port>` and `uav-api` will POST the vehicle's GPS position to the Gradys GS every second:

```bash
uav-mcp --port 8000 --sysid 1 --gradys_gs 192.168.1.10:5000
```

## Visual Feedback with Mission Planner

In simulated mode, use `--gs_connection` to stream MAVLink telemetry to Mission Planner (or any GCS):

```bash
uav-mcp --simulated true --ardupilot_path ~/ardupilot --sysid 1 --gs_connection 192.168.1.5:14550
```

![image](https://github.com/user-attachments/assets/b7928581-89c6-46c0-9f02-3bd8edd30570)
