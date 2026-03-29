# UAV MCP

Pure MCP server for controlling ArduPilot-compatible UAVs (QuadCopters). Exposes drone command, movement, and telemetry as **MCP tools** via Streamable HTTP, powered by the [official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk). Supports real drones via MAVLink and simulated drones via ArduPilot SITL.

**Features:**
- **MCP tool interface** at `/mcp` — connect any MCP client (Claude Desktop, Claude Code, LangGraph, custom agents) to control drones
- Full flight control: arm and takeoff in a single command
- GPS and NED movement commands (fire-and-forget and blocking variants)
- Rich telemetry: GPS, NED position, compass, battery, sensor health
- Gradys Ground Station integration: periodic GPS location push
- Visual feedback via Mission Planner or any MAVLink GCS
- Configurable logging per component

---

# Installation

## Prerequisites

- Python 3.10+
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

## Running with a real drone

Connect your drone via UDP or USB, then start the MCP server:

```bash
uav-mcp --port 8000 --uav_connection 127.0.0.1:17171 --connection_type udpin --sysid 1
```

The `--connection_type` controls the UDP direction:
- `udpin` — server listens, drone connects to it (most common)
- `udpout` — server connects out to the drone
- `usb` — serial connection (set `--uav_connection` to the serial device path, e.g. `/dev/ttyUSB0`)

## Running in simulation (SITL)

This starts both ArduCopter SITL (in a new `xterm` window) and the MCP server:

```bash
uav-mcp --simulated true --ardupilot_path ~/ardupilot --speedup 1 --port 8000 --sysid 1
```

SITL will bind to the address in `--uav_connection` (default `127.0.0.1:17171`). The `--speedup` factor controls simulation speed (e.g. `5` = 5x real time). The `--location` argument sets the SITL home position (default `AbraDF`).

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

When `uav-mcp` starts, the following happens sequentially in `run_mcp.py`:

**Startup:**
1. CLI arguments are parsed and directories are set up
2. If `--simulated true`: SITL is spawned in an xterm window (tagged with `UAV_SITL_TAG` env var for cleanup)
3. The `Copter` singleton is created and connects to the MAVLink vehicle
4. A background MAVLink drain loop is started (`asyncio.create_task`)
5. If `--gradys_gs` is set: a background task starts pushing GPS location every second
6. The MCP server starts listening on the configured port (`mcp.run_streamable_http_async()`)

**Shutdown** (on Ctrl+C or SIGTERM):
1. SITL processes are killed by scanning for the `UAV_SITL_TAG` env var via `psutil`
2. The MAVLink drain loop is cancelled
3. The Gradys GS task is cancelled and the HTTP session is closed

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

Run one MCP server per drone with different ports and sysids:

```bash
uav-mcp --simulated true --ardupilot_path ~/ardupilot --port 8001 --sysid 1
uav-mcp --simulated true --ardupilot_path ~/ardupilot --port 8002 --sysid 2
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

See `.claude/docs/specification.md` for full parameter and response details.

---

# CLI Arguments Reference

All arguments can be passed on the command line or set in an INI config file. Run `uav-mcp --help` for a quick reference.

## General (all modes)

| Argument | Default | Description |
|----------|---------|-------------|
| `--config` | None | Path to INI config file (`[api]`, `[simulated]`, `[logs]` sections) |
| `--port` | 8000 | Port the MCP server listens on (streamable HTTP) |
| `--sysid` | 10 | MAVLink system ID; must match the drone's `SYSID_THISMAV` parameter |
| `--uav_connection` | `127.0.0.1:17171` | MAVLink address — `host:port` for UDP, or serial device path for USB |
| `--gradys_gs` | None | `host:port` of Gradys Ground Station — enables periodic GPS location push |
| `--scripts_path` | `~/uav_scripts` | Directory where mission scripts are saved |
| `--python_path` | `python3` | Python binary used to run scripts |

## Connection (real drone)

| Argument | Default | Description |
|----------|---------|-------------|
| `--connection_type` | `udpin` | `udpin` — server listens; `udpout` — server connects out; `usb` — serial |

## Simulation only

| Argument | Default | Description |
|----------|---------|-------------|
| `--simulated` | `false` | Set to `true` to spawn ArduCopter SITL alongside the MCP server |
| `--ardupilot_path` | `~/ardupilot` | Path to local ArduPilot repository |
| `--location` | `AbraDF` | Named home position for SITL (defined in `~/.config/ardupilot/locations.txt`) |
| `--speedup` | 1 | SITL simulation time multiplier |
| `--gs_connection` | `[]` | Extra `host:port` addresses SITL streams telemetry to (e.g. Mission Planner) |

## Logging

| Argument | Default | Description |
|----------|---------|-------------|
| `--log_console` | `[]` | Components to print logs to console: `COPTER` `GRADYS_GS` |
| `--log_path` | None | File path to write all component logs combined |
| `--debug` | `[]` | Same component names as `--log_console` but at DEBUG verbosity |
| `--script_logs` | None | Directory where script stdout/stderr are saved as timestamped `.log` files |

---

# Extra Features

## Gradys Ground Station Integration

When `--gradys_gs <host:port>` is set, the server starts a background coroutine that POSTs the vehicle's GPS position to the Gradys GS every second:

```bash
uav-mcp --port 8000 --sysid 1 --gradys_gs 192.168.1.10:5000
```

Each POST to `http://<gradys_gs>/update-info/` includes: latitude, longitude, altitude, device type, a sequence number, and the server's own IP and port. This allows the Gradys ecosystem to track the UAV in real time.

## Visual Feedback with Mission Planner

When running in simulated mode, use `--gs_connection` to stream MAVLink telemetry to Mission Planner (or any GCS software):

```bash
uav-mcp --simulated true --ardupilot_path ~/ardupilot --sysid 1 --gs_connection [192.168.1.5:14550]
```

Connect Mission Planner to the specified UDP address to see live position, attitude, and flight data.

![image](https://github.com/user-attachments/assets/b7928581-89c6-46c0-9f02-3bd8edd30570)

## Logging System

Control what gets logged and where with the logging arguments:

```bash
# Print COPTER logs to console
uav-mcp --log_console COPTER ...

# Write all logs to a file
uav-mcp --log_path ~/uav_mcp.log ...

# Enable DEBUG verbosity for the COPTER component
uav-mcp --debug COPTER ...
```

Available log components: `COPTER`, `GRADYS_GS`.
