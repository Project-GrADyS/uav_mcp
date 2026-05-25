
import configparser
import json
import argparse
import os

def namespace_to_str(namespace: argparse.Namespace) -> str:
    """Convert argparse.Namespace to a JSON string."""
    return json.dumps(vars(namespace))

def str_to_namespace(s: str) -> argparse.Namespace:
    """Convert JSON string back to argparse.Namespace."""
    data = json.loads(s)
    return argparse.Namespace(**data)

def write_args_to_env(args):
    os.environ['UAV_ARGS'] = namespace_to_str(args)

def read_args_from_env() -> argparse.Namespace:
    """Read UAV_ARGS from environment variable and convert it back to argparse.Namespace."""
    args_str = os.getenv('UAV_ARGS')
    if args_str:
        return str_to_namespace(args_str)
    return None

def parse_args(raw_args=None):
    parser = argparse.ArgumentParser(description="Welcome to the UAV MCP Runner. Starts an MCP server that proxies tool calls to a uav_api HTTP server (spawned locally or external).")
    parse_mode(parser)
    parse_mcp(parser)
    parse_uav_api(parser)
    parse_logs(parser)
    parse_simulated(parser)
    args = parser.parse_args(raw_args)

    if args.config:
        config = configparser.ConfigParser()
        config.read(args.config)

        if "simulated" in config.sections():
            setattr(args, "simulated", True)

        for section in config.sections():
            for key, value in config.items(section):
                if hasattr(args, key):
                    if value[0] == "[":
                        value = value.strip("[]").split(",")
                        value = [v.strip() for v in value]
                    setattr(args, key, value)
                else:
                    print(f"Warning: {key} not found in args")
    return args

# MODE PARSER
def parse_mode(mode_parser):

    mode_parser.add_argument(
        '--simulated',
        dest='simulated',
        type=bool,
        default=False,
        help="Whether to simulate copter using ArduPilot's SITL. Passed through to the spawned uav-api."
    )

    mode_parser.add_argument(
        '--config',
        dest='config',
        default=None,
        help="Configuration file for UAV execution"
    )

# MCP PARSER (uav_mcp-owned args)
def parse_mcp(mcp_parser):

    mcp_parser.add_argument(
        '--port',
        dest='port',
        type=int,
        default=8000,
        help='Port the MCP server (streamable HTTP) listens on'
    )

    mcp_parser.add_argument(
        '--uav_api_url',
        dest='uav_api_url',
        default=None,
        help='URL of an already-running uav_api. If set, uav_mcp connects to it instead of spawning its own.'
    )

    mcp_parser.add_argument(
        '--uav_api_port',
        dest='uav_api_port',
        type=int,
        default=8001,
        help='Port the spawned uav-api subprocess listens on (ignored when --uav_api_url is set).'
    )

# UAV API PARSER (passed through to spawned uav-api)
def parse_uav_api(api_parser):

    api_parser.add_argument(
        '--uav_connection',
        dest='uav_connection',
        default='127.0.0.1:17171',
        help='Address used for copter connection (passed through to uav-api)'
    )

    api_parser.add_argument(
        '--connection_type',
        dest='connection_type',
        default='udpin',
        help="Connection type for copter (udpin, udpout, usb). Passed through to uav-api."
    )

    api_parser.add_argument(
        '--sysid',
        dest='sysid',
        type=int,
        default=10,
        help='MAVLink system ID. Passed through to uav-api.'
    )

    api_parser.add_argument(
        '--gradys_gs',
        dest='gradys_gs',
        type=str,
        default=None,
        help='Address for Gradys Ground Station. When set, uav-api pushes GPS location every second.'
    )

    api_parser.add_argument(
        '--scripts_path',
        dest='scripts_path',
        type=str,
        default="~/uav_scripts",
        help='Path for uav_scripts directory (passed through to uav-api)'
    )

    api_parser.add_argument(
        '--python_path',
        dest='python_path',
        type=str,
        default="python3",
        help='Python binary used by uav-api to run scripts'
    )
# SIMULATED PARSER
def parse_simulated(simulated_parser):

    simulated_parser.add_argument(
        '--location',
        dest='location',
        default="AbraDF",
        help="""Named home location for SITL (passed through to uav-api). To register a new location,
            run `bash scripts/registry_location [LOCATION_NAME] [GPS_LAT] [GPS_LONG] [GPS_ALT] [HEADING]` in the uav_api repo.
        """
    )

    simulated_parser.add_argument(
        '--gs_connection',
        dest='gs_connection',
        default=[],
        help="Extra host:port addresses SITL streams telemetry to (e.g. Mission Planner)",
        nargs='*'
    )

    simulated_parser.add_argument(
        '--speedup',
        dest='speedup',
        type=int,
        default=1,
        help="SITL simulation time multiplier (passed through to uav-api)"
    )

    simulated_parser.add_argument(
        '--ardupilot_path',
        dest='ardupilot_path',
        default='~/ardupilot',
        help="Path to local ArduPilot repository (passed through to uav-api)"
    )

def parse_logs(logs_parser):

    logs_parser.add_argument(
        "--log_console",
        dest="log_console",
        default=[],
        help="Loggers to print to console. Passed through to uav-api (valid values: API, COPTER, GRADYS_GS).",
        nargs='*'
    )

    logs_parser.add_argument(
        "--log_path",
        dest="log_path",
        default=None,
        help="File path for combined uav-api logs (passed through)."
    )

    logs_parser.add_argument(
        "--debug",
        dest="debug",
        default=[],
        help="Loggers to set to DEBUG level. Passed through to uav-api.",
        nargs="*"
    )

    logs_parser.add_argument(
        "--script_logs",
        dest="script_logs",
        default=None,
        help="Directory where uav-api saves stdout/stderr of executed scripts (passed through)."
    )
