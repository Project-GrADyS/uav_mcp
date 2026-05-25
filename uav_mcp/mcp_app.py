import os
import json
import asyncio
import subprocess
from typing import Optional

import aiohttp
import psutil

from mcp.server.fastmcp import FastMCP
from uav_mcp.args import read_args_from_env
from uav_mcp import uav_api_client

args = read_args_from_env()

UAV_API_TAG_ENV = "UAV_MCP_API_TAG"


def _api_tag() -> str:
    return f"MCP_API_{args.sysid}"


def base_url() -> str:
    return args.uav_api_url or f"http://127.0.0.1:{args.uav_api_port}"


def start_uav_api() -> Optional[str]:
    """Spawn uav-api as a subprocess unless an external URL is configured.

    Returns the tag string used to identify spawned processes for shutdown,
    or None when uav_mcp is talking to an external uav_api.
    """
    if args.uav_api_url:
        print(f"Using external uav-api at {args.uav_api_url}")
        return None

    tag = _api_tag()
    env = os.environ.copy()
    env[UAV_API_TAG_ENV] = tag

    cmd = [
        "uav-api",
        "--port", str(args.uav_api_port),
        "--sysid", str(args.sysid),
        "--uav_connection", args.uav_connection,
        "--connection_type", args.connection_type,
        "--scripts_path", args.scripts_path,
        "--python_path", args.python_path,
    ]
    if args.simulated:
        cmd += [
            "--simulated", "true",
            "--ardupilot_path", args.ardupilot_path,
            "--location", args.location,
            "--speedup", str(args.speedup),
        ]
        for gs in (args.gs_connection or []):
            cmd += ["--gs_connection", gs]
    if args.gradys_gs:
        cmd += ["--gradys_gs", args.gradys_gs]
    if args.log_path:
        cmd += ["--log_path", args.log_path]
    if args.script_logs:
        cmd += ["--script_logs", args.script_logs]
    for lg in (args.log_console or []):
        cmd += ["--log_console", lg]
    for lg in (args.debug or []):
        cmd += ["--debug", lg]

    print(f"Spawning uav-api on port {args.uav_api_port} (tag={tag})...")
    subprocess.Popen(cmd, env=env)
    return tag


def kill_uav_api_by_tag(tag: str) -> None:
    """Kill any process whose environment carries the given UAV_MCP_API_TAG."""
    for proc in psutil.process_iter(['environ', 'name', 'pid']):
        try:
            proc_env = proc.info.get('environ')
            if proc_env and proc_env.get(UAV_API_TAG_ENV) == tag:
                print(f"Killing spawned process {proc.info['name']} (PID {proc.info['pid']})")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue


async def wait_for_uav_api(url: str, timeout: float = 120.0) -> None:
    """Poll `url`/docs until uav_api responds or `timeout` seconds elapse."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(
                    f"{url}/docs",
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as resp:
                    if resp.status < 500:
                        print(f"uav-api ready at {url}")
                        return
            except Exception:
                pass
            if loop.time() > deadline:
                raise RuntimeError(f"uav-api did not become ready at {url} within {timeout}s")
            await asyncio.sleep(1.0)


mcp = FastMCP(
    "UAV MCP Server",
    instructions=(
        "MCP server for controlling an ArduPilot UAV. Tools are organized in three groups: "
        "'command' (arm_and_takeoff), 'movement' (GPS/NED navigation, stop/resume), and "
        "'telemetry' (position, battery, sensors). Always arm_and_takeoff before issuing "
        "movement commands. Use '_wait' variants of movement tools for sequential waypoint navigation."
    ),
    host="0.0.0.0",
    port=args.port,
)


def _ok(result: str, **extra) -> str:
    body = {"device": "uav", "id": str(args.sysid), "result": result}
    body.update(extra)
    return json.dumps(body)


def _err(tool: str, e: Exception) -> str:
    return json.dumps({"device": "uav", "id": str(args.sysid), "error": f"{tool} FAIL: {e}"})


# ──────────────────────────── Command Tools ────────────────────────────

@mcp.tool()
async def arm_and_takeoff(alt: int = 15) -> str:
    """Arms the vehicle and takes off to the specified altitude. Switches to GUIDED mode,
    waits until the vehicle is ready to arm, arms the motors, then commands vertical takeoff.
    Blocks until the target altitude is reached. MUST be called before any movement commands.
    Parameter 'alt' is altitude in meters above the launch point (default: 15m)."""
    try:
        await uav_api_client.get("/command/arm")
        await uav_api_client.get("/command/takeoff", params={"alt": alt})
    except Exception as e:
        return _err("ARM_AND_TAKEOFF", e)
    return _ok(f"Armed and took off to {alt} meters")


# ──────────────────────────── Movement Tools ────────────────────────────

@mcp.tool()
async def go_to_gps(lat: float, long: float, alt: float, look_at_target: bool = False) -> str:
    """Fly to GPS coordinates (non-blocking). Commands the vehicle to fly to the specified
    GPS position. Returns immediately after sending the command — does NOT wait for arrival.
    Use 'go_to_gps_wait' if you need to wait until the vehicle arrives.
    Coordinates: lat/long in decimal degrees, alt in meters above sea level.
    Set look_at_target=true to yaw toward the destination."""
    try:
        body = await uav_api_client.post(
            "/movement/go_to_gps/",
            {"lat": lat, "long": long, "alt": alt, "look_at_target": look_at_target},
        )
    except Exception as e:
        return _err("GO_TO_GPS", e)
    return json.dumps(body)


@mcp.tool()
async def go_to_gps_wait(lat: float, long: float, alt: float, look_at_target: bool = False) -> str:
    """Fly to GPS coordinates and wait for arrival. Commands the vehicle to fly to the
    specified GPS position and blocks until arrival (timeout: 60s). Use this when you need
    to execute sequential waypoints. Coordinates: lat/long in decimal degrees,
    alt in meters above sea level."""
    try:
        body = await uav_api_client.post(
            "/movement/go_to_gps_wait",
            {"lat": lat, "long": long, "alt": alt, "look_at_target": look_at_target},
        )
    except Exception as e:
        return _err("GO_TO_GPS_WAIT", e)
    return json.dumps(body)


@mcp.tool()
async def go_to_ned(x: float, y: float, z: float, look_at_target: bool = False) -> str:
    """Fly to NED position (non-blocking). Commands the vehicle to fly to an absolute position
    in the NED (North-East-Down) coordinate frame, relative to HOME. Returns immediately.
    Use 'go_to_ned_wait' to wait. Axes: x=North(+)/South(-), y=East(+)/West(-),
    z=Down(+)/Up(-), all in meters. Set look_at_target=true to yaw toward the destination."""
    try:
        body = await uav_api_client.post(
            "/movement/go_to_ned",
            {"x": x, "y": y, "z": z, "look_at_target": look_at_target},
        )
    except Exception as e:
        return _err("GO_TO_NED", e)
    return json.dumps(body)


@mcp.tool()
async def go_to_ned_wait(x: float, y: float, z: float, look_at_target: bool = False) -> str:
    """Fly to NED position and wait for arrival. Commands the vehicle to fly to an absolute
    NED position and blocks until arrival (timeout: 60s). Use for sequential waypoint
    navigation in local coordinates. Axes: x=North(+)/South(-), y=East(+)/West(-),
    z=Down(+)/Up(-), all in meters."""
    try:
        body = await uav_api_client.post(
            "/movement/go_to_ned_wait",
            {"x": x, "y": y, "z": z, "look_at_target": look_at_target},
        )
    except Exception as e:
        return _err("GO_TO_NED_WAIT", e)
    return json.dumps(body)


@mcp.tool()
async def drive(x: float, y: float, z: float, look_at_target: bool = False) -> str:
    """Move by relative offset (non-blocking). Commands the vehicle to move by a relative
    offset from its CURRENT position in the NED frame. Returns immediately.
    Unlike go_to_ned which uses absolute positions from HOME, drive moves relative to where
    the vehicle is right now. Axes: x=North(+)/South(-), y=East(+)/West(-),
    z=Down(+)/Up(-), all in meters."""
    try:
        body = await uav_api_client.post(
            "/movement/drive",
            {"x": x, "y": y, "z": z, "look_at_target": look_at_target},
        )
    except Exception as e:
        return _err("DRIVE", e)
    return json.dumps(body)


@mcp.tool()
async def drive_wait(x: float, y: float, z: float, look_at_target: bool = False) -> str:
    """Move by relative offset and wait. Commands the vehicle to move by a relative offset
    from its current position and blocks until arrival (timeout: 60s). Use for precise
    relative movements like 'move 10 meters north'. Axes: x=North(+)/South(-),
    y=East(+)/West(-), z=Down(+)/Up(-), all in meters."""
    try:
        body = await uav_api_client.post(
            "/movement/drive_wait",
            {"x": x, "y": y, "z": z, "look_at_target": look_at_target},
        )
    except Exception as e:
        return _err("DRIVE_WAIT", e)
    return json.dumps(body)


@mcp.tool()
async def stop() -> str:
    """Stop all movement immediately. Halts the vehicle at its current position. Cancels any
    ongoing movement command (go_to, drive). The vehicle will hold its current position
    until a new movement command is issued or 'resume' is called."""
    try:
        body = await uav_api_client.get("/movement/stop")
    except Exception as e:
        return _err("STOP", e)
    return json.dumps(body)


@mcp.tool()
async def resume() -> str:
    """Resume previous movement. Resumes the last movement command that was interrupted
    by 'stop'. Only useful after a 'stop' command was issued."""
    try:
        body = await uav_api_client.get("/movement/resume")
    except Exception as e:
        return _err("RESUME", e)
    return json.dumps(body)


# ──────────────────────────── Telemetry Tools ────────────────────────────

@mcp.tool()
async def get_general_telemetry() -> str:
    """Get flight overview. Returns airspeed (m/s), groundspeed (m/s), heading (degrees 0-360),
    throttle (percentage 0-100), and barometric altitude (meters). Use this for a quick
    status check of the vehicle's flight state."""
    try:
        body = await uav_api_client.get("/telemetry/general")
    except Exception as e:
        return _err("GET_GENERAL_INFO", e)
    return json.dumps(body)


@mcp.tool()
async def get_gps() -> str:
    """Get fused GPS position. Returns the vehicle's current position from sensor fusion
    (GPS + accelerometers + barometer). More accurate than raw GPS. Includes: lat/lon (degrees),
    altitude (meters ASL), relative altitude (meters above HOME), velocity components
    vx/vy/vz (m/s), and heading (degrees). Use this as the primary position source."""
    try:
        body = await uav_api_client.get("/telemetry/gps")
    except Exception as e:
        return _err("GET_GPS", e)
    return json.dumps(body)


@mcp.tool()
async def get_ned() -> str:
    """Get local NED position and velocity. Returns the vehicle's position and velocity in
    the NED (North-East-Down) local coordinate frame, relative to HOME. Position: x/y/z
    in meters. Velocity: vx/vy/vz in m/s. Use this when working with go_to_ned, drive
    commands — the coordinate frame matches."""
    try:
        body = await uav_api_client.get("/telemetry/ned")
    except Exception as e:
        return _err("GET_NED", e)
    return json.dumps(body)


@mcp.tool()
async def get_compass() -> str:
    """Get compass calibration status. Returns calibration status, whether it was auto-saved,
    and fitness values (x/y/z). Use for pre-flight diagnostics — poor compass calibration
    can cause navigation issues."""
    try:
        body = await uav_api_client.get("/telemetry/compass")
    except Exception as e:
        return _err("GET_COMPASS", e)
    return json.dumps(body)


@mcp.tool()
async def get_sys_status() -> str:
    """Get raw system status. Returns the complete raw SYS_STATUS MAVLink message as a
    dictionary. Contains detailed system health data. For most use cases, prefer the more
    specific tools: get_battery, get_sensor_status."""
    try:
        body = await uav_api_client.get("/telemetry/sys_status")
    except Exception as e:
        return _err("GET_SYS_STATUS", e)
    return json.dumps(body)


@mcp.tool()
async def get_sensor_status() -> str:
    """Get sensor health flags. Returns parsed sensor health flags from SYS_STATUS. Shows
    which sensors are present, enabled, and healthy. Use for pre-flight checks or
    diagnosing sensor failures."""
    try:
        body = await uav_api_client.get("/telemetry/sensor_status")
    except Exception as e:
        return _err("GET_SENSOR_STATUS", e)
    return json.dumps(body)


@mcp.tool()
async def get_battery() -> str:
    """Get battery status. Returns battery voltage (mV) and current draw (mA). Monitor this
    to ensure safe flight duration — land or RTL when battery is low. Critical for
    autonomous mission planning."""
    try:
        body = await uav_api_client.get("/telemetry/battery_info")
    except Exception as e:
        return _err("GET_BATTERY", e)
    return json.dumps(body)


@mcp.tool()
async def get_home() -> str:
    """Get HOME position. Returns the HOME position in both GPS (lat/lon/altitude in
    degrees/meters) and NED (x/y/z in meters) coordinates. HOME is the origin (0,0,0)
    of the NED frame and the RTL destination. Use this to understand the reference frame
    for NED-based navigation."""
    try:
        body = await uav_api_client.get("/telemetry/home_info")
    except Exception as e:
        return _err("GET_HOME", e)
    return json.dumps(body)
