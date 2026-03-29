import os
import json
import asyncio
import aiohttp
import psutil
import subprocess

from mcp.server.fastmcp import FastMCP
from uav_mcp.copter import Copter
from uav_mcp.classes.movement import Local_pos
from uav_mcp.log import set_log_config
from uav_mcp.args import read_args_from_env
from uav_mcp.gradys_gs import send_location_to_gradys_gs

args = read_args_from_env()

# Module-level state, initialized by run_mcp.py before the server starts
copter_instance = None


def kill_sitl_by_tag(tag_value):
    """Scans ALL system processes and kills those with the matching environment tag."""
    for proc in psutil.process_iter(['environ', 'name', 'pid']):
        try:
            env = proc.info.get('environ')
            if env and env.get("UAV_SITL_TAG") == tag_value:
                print(f"Found rogue process: {proc.info['name']} (PID: {proc.info['pid']}). Killing...")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue


def start_sitl(args):
    """Starts SITL if in simulated mode. Returns the sitl_tag or None."""
    if not args.simulated:
        return None

    print("Starting SITL...")
    sitl_tag = f"SITL_ID_{args.sysid}"

    env = os.environ.copy()
    env["UAV_SITL_TAG"] = sitl_tag

    ardupilot_base = os.path.expanduser(args.ardupilot_path)
    script_path = os.path.join(ardupilot_base, "Tools/autotest/sim_vehicle.py")

    out_str = f"--out {args.uav_connection} {' '.join([f'--out {address}' for address in args.gs_connection])} "
    home_dir = os.path.expanduser("~")
    ardupilot_logs = os.path.join(home_dir, "uav_mcp_logs", "ardupilot_logs")
    sitl_command = f"xterm -e {script_path} -v ArduCopter -I {args.sysid} --sysid {args.sysid} -N -L {args.location} --speedup {args.speedup} {out_str} --use-dir={ardupilot_logs}"

    sitl_process = subprocess.Popen(sitl_command.split(" "), env=env)
    print(f"SITL started with PID {sitl_process.pid}.")
    return sitl_tag


def start_copter(args):
    """Creates and connects the Copter singleton. Returns the instance."""
    global copter_instance
    set_log_config(args)
    connection = args.uav_connection if args.connection_type == "usb" else f"{args.connection_type}:{args.uav_connection}"
    copter_instance = Copter(sysid=int(args.sysid))
    copter_instance.connect(connection_string=connection)
    return copter_instance


async def start_gradys_gs(args, copter):
    """Starts the Gradys GS location push task if configured. Returns (task, session) or (None, None)."""
    if args.gradys_gs is None:
        return None, None

    print("Starting Gradys GS location task...")
    session = aiohttp.ClientSession()
    task = asyncio.create_task(
        send_location_to_gradys_gs(copter, session, args.port, args.gradys_gs)
    )
    return task, session


mcp = FastMCP(
    "UAV MCP Server",
    instructions="MCP server for controlling an ArduPilot UAV. Tools are organized in three groups: 'command' (arm_and_takeoff), 'movement' (GPS/NED navigation, stop/resume), and 'telemetry' (position, battery, sensors). Always arm_and_takeoff before issuing movement commands. Use '_wait' variants of movement tools for sequential waypoint navigation.",
    host="0.0.0.0",
    port=args.port,
)


def _get():
    """Returns the copter instance and args. Used by all tools."""
    return copter_instance, args


# ──────────────────────────── Command Tools ────────────────────────────

@mcp.tool()
def arm_and_takeoff(alt: int = 15) -> str:
    """Arms the vehicle and takes off to the specified altitude. Switches to GUIDED mode,
    waits until the vehicle is ready to arm, arms the motors, then commands vertical takeoff.
    Blocks until the target altitude is reached. MUST be called before any movement commands.
    Parameter 'alt' is altitude in meters above the launch point (default: 15m)."""
    copter, a = _get()
    try:
        copter.change_mode("GUIDED")
        copter.wait_ready_to_arm()
        copter.arm_vehicle()
        copter.user_takeoff(alt)
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"ARM_AND_TAKEOFF FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": f"Armed and took off to {alt} meters"})


# ──────────────────────────── Movement Tools ────────────────────────────

@mcp.tool()
def go_to_gps(lat: float, long: float, alt: float, look_at_target: bool = False) -> str:
    """Fly to GPS coordinates (non-blocking). Commands the vehicle to fly to the specified
    GPS position. Returns immediately after sending the command — does NOT wait for arrival.
    Use 'go_to_gps_wait' if you need to wait until the vehicle arrives.
    Coordinates: lat/long in decimal degrees, alt in meters above sea level.
    Set look_at_target=true to yaw toward the destination."""
    copter, a = _get()
    try:
        copter.go_to_gps(lat, long, alt, look_at_target)
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GO_TO_GPS FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": f"Going to coord ({lat}, {long}, {alt})"})


@mcp.tool()
def go_to_gps_wait(lat: float, long: float, alt: float, look_at_target: bool = False) -> str:
    """Fly to GPS coordinates and wait for arrival. Commands the vehicle to fly to the
    specified GPS position and blocks until arrival (timeout: 60s). Use this when you need
    to execute sequential waypoints. Coordinates: lat/long in decimal degrees,
    alt in meters above sea level."""
    copter, a = _get()
    try:
        copter.go_to_gps(lat, long, alt, look_at_target)
        target_loc = copter.mav_location(lat, long, alt)
        copter.wait_location(target_loc, timeout=60)
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GO_TO_GPS_WAIT FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": f"Arrived at coord ({lat}, {long}, {alt})"})


@mcp.tool()
def go_to_ned(x: float, y: float, z: float, look_at_target: bool = False) -> str:
    """Fly to NED position (non-blocking). Commands the vehicle to fly to an absolute position
    in the NED (North-East-Down) coordinate frame, relative to HOME. Returns immediately.
    Use 'go_to_ned_wait' to wait. Axes: x=North(+)/South(-), y=East(+)/West(-),
    z=Down(+)/Up(-), all in meters. Set look_at_target=true to yaw toward the destination."""
    copter, a = _get()
    try:
        copter.go_to_ned(x, y, z, look_at_target=look_at_target)
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GO_TO_NED FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": f"Going to NED coord ({x}, {y}, {z})"})


@mcp.tool()
def go_to_ned_wait(x: float, y: float, z: float, look_at_target: bool = False) -> str:
    """Fly to NED position and wait for arrival. Commands the vehicle to fly to an absolute
    NED position and blocks until arrival (timeout: 60s). Use for sequential waypoint
    navigation in local coordinates. Axes: x=North(+)/South(-), y=East(+)/West(-),
    z=Down(+)/Up(-), all in meters."""
    copter, a = _get()
    try:
        copter.go_to_ned(x, y, z, look_at_target=look_at_target)
        target = Local_pos(x=x, y=y, z=z)
        copter.wait_ned_position(target)
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GO_TO_NED_WAIT FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": f"Arrived at NED coord ({x}, {y}, {z})"})


@mcp.tool()
def drive(x: float, y: float, z: float, look_at_target: bool = False) -> str:
    """Move by relative offset (non-blocking). Commands the vehicle to move by a relative
    offset from its CURRENT position in the NED frame. Returns immediately.
    Unlike go_to_ned which uses absolute positions from HOME, drive moves relative to where
    the vehicle is right now. Axes: x=North(+)/South(-), y=East(+)/West(-),
    z=Down(+)/Up(-), all in meters."""
    copter, a = _get()
    try:
        copter.drive_ned(x, y, z, look_at_target=look_at_target)
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"DRIVE FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": "Copter is driving"})


@mcp.tool()
def drive_wait(x: float, y: float, z: float, look_at_target: bool = False) -> str:
    """Move by relative offset and wait. Commands the vehicle to move by a relative offset
    from its current position and blocks until arrival (timeout: 60s). Use for precise
    relative movements like 'move 10 meters north'. Axes: x=North(+)/South(-),
    y=East(+)/West(-), z=Down(+)/Up(-), all in meters."""
    copter, a = _get()
    try:
        current_pos = copter.get_ned_position()
        copter.drive_ned(x, y, z, look_at_target=look_at_target)
        target_pos = Local_pos(x=current_pos.x + x, y=current_pos.y + y, z=current_pos.z + z)
        copter.wait_ned_position(target_pos)
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"DRIVE_WAIT FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": f"Copter arrived at ({target_pos.x}, {target_pos.y}, {target_pos.z})"})


@mcp.tool()
def stop() -> str:
    """Stop all movement immediately. Halts the vehicle at its current position. Cancels any
    ongoing movement command (go_to, drive). The vehicle will hold its current position
    until a new movement command is issued or 'resume' is called."""
    copter, a = _get()
    try:
        copter.stop()
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"STOP FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": "Copter has stopped"})


@mcp.tool()
def resume() -> str:
    """Resume previous movement. Resumes the last movement command that was interrupted
    by 'stop'. Only useful after a 'stop' command was issued."""
    copter, a = _get()
    try:
        copter.resume()
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"RESUME FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": "Copter has resumed movement"})


# ──────────────────────────── Telemetry Tools ────────────────────────────

@mcp.tool()
def get_general_telemetry() -> str:
    """Get flight overview. Returns airspeed (m/s), groundspeed (m/s), heading (degrees 0-360),
    throttle (percentage 0-100), and barometric altitude (meters). Use this for a quick
    status check of the vehicle's flight state."""
    copter, a = _get()
    try:
        info = copter.get_general_info()
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GET_GENERAL_INFO FAIL: {e}"})
    return json.dumps({
        "device": "uav", "id": str(a.sysid), "result": "Success",
        "info": {
            "airspeed": info.airspeed,
            "groundspeed": info.groundspeed,
            "heading": info.heading,
            "throttle": info.throttle,
            "alt": info.alt
        }
    })


@mcp.tool()
def get_gps() -> str:
    """Get fused GPS position. Returns the vehicle's current position from sensor fusion
    (GPS + accelerometers + barometer). More accurate than raw GPS. Includes: lat/lon (degrees),
    altitude (meters ASL), relative altitude (meters above HOME), velocity components
    vx/vy/vz (m/s), and heading (degrees). Use this as the primary position source."""
    copter, a = _get()
    try:
        info = copter.get_gps_info()
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GET_GPS FAIL: {e}"})
    return json.dumps({
        "device": "uav", "id": str(a.sysid), "result": "Success",
        "info": {
            "position": {
                "lat": info.lat / 1.0e7,
                "lon": info.lon / 1.0e7,
                "alt": info.alt / 1000,
                "relative_alt": info.relative_alt / 1000,
            },
            "velocity": {
                "vx": info.vx / 100,
                "vy": info.vy / 100,
                "vz": info.vz / 100,
            },
            "heading": info.hdg / 100
        }
    })


@mcp.tool()
def get_ned() -> str:
    """Get local NED position and velocity. Returns the vehicle's position and velocity in
    the NED (North-East-Down) local coordinate frame, relative to HOME. Position: x/y/z
    in meters. Velocity: vx/vy/vz in m/s. Use this when working with go_to_ned, drive
    commands — the coordinate frame matches."""
    copter, a = _get()
    try:
        info = copter.get_ned_info()
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GET_NED FAIL: {e}"})
    return json.dumps({
        "device": "uav", "id": str(a.sysid), "result": "Success",
        "info": {
            "position": {"x": info.x, "y": info.y, "z": info.z},
            "velocity": {"vx": info.vx, "vy": info.vy, "vz": info.vz}
        }
    })


@mcp.tool()
def get_compass() -> str:
    """Get compass calibration status. Returns calibration status, whether it was auto-saved,
    and fitness values (x/y/z). Use for pre-flight diagnostics — poor compass calibration
    can cause navigation issues."""
    copter, a = _get()
    try:
        info = copter.get_compass_info()
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GET_COMPASS FAIL: {e}"})
    return json.dumps({
        "device": "uav", "id": str(a.sysid), "result": "Success",
        "info": {
            "calibration_status": info.calibration_status,
            "autosaved": bool(info.autosaved),
            "fitness": {
                "x": info.fitness[0],
                "y": info.fitness[1],
                "z": info.fitness[2]
            }
        }
    })


@mcp.tool()
def get_sys_status() -> str:
    """Get raw system status. Returns the complete raw SYS_STATUS MAVLink message as a
    dictionary. Contains detailed system health data. For most use cases, prefer the more
    specific tools: get_battery, get_sensor_status."""
    copter, a = _get()
    try:
        status_message = copter.get_raw_status_message()
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GET_SYS_STATUS FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": "success", "status": status_message.to_dict()})


@mcp.tool()
def get_sensor_status() -> str:
    """Get sensor health flags. Returns parsed sensor health flags from SYS_STATUS. Shows
    which sensors are present, enabled, and healthy. Use for pre-flight checks or
    diagnosing sensor failures."""
    copter, a = _get()
    try:
        sensor_status = copter.get_sensor_status()
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GET_SENSOR_STATUS FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": "success", "status": sensor_status})


@mcp.tool()
def get_battery() -> str:
    """Get battery status. Returns battery voltage (mV) and current draw (mA). Monitor this
    to ensure safe flight duration — land or RTL when battery is low. Critical for
    autonomous mission planning."""
    copter, a = _get()
    try:
        info = copter.get_battery_info()
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GET_BATTERY FAIL: {e}"})
    return json.dumps({"device": "uav", "id": str(a.sysid), "result": "success", "info": info})


@mcp.tool()
def get_home() -> str:
    """Get HOME position. Returns the HOME position in both GPS (lat/lon/altitude in
    degrees/meters) and NED (x/y/z in meters) coordinates. HOME is the origin (0,0,0)
    of the NED frame and the RTL destination. Use this to understand the reference frame
    for NED-based navigation."""
    copter, a = _get()
    try:
        info = copter.get_home_position()
    except Exception as e:
        return json.dumps({"device": "uav", "id": str(a.sysid), "error": f"GET_HOME FAIL: {e}"})
    return json.dumps({
        "device": "uav", "id": str(a.sysid), "result": "Success",
        "lat": info["latitude"] / 1.0e7,
        "lon": info["longitude"] / 1.0e7,
        "altitude": info["altitude"] / 1000,
        "x": info["x"],
        "y": info["y"],
        "z": info["z"]
    })
