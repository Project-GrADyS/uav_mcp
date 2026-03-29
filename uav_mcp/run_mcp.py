import asyncio

import anyio

from uav_mcp.args import parse_args, write_args_to_env
from uav_mcp.setup import setup


async def _run():
    from uav_mcp.mcp_app import (
        mcp,
        args,
        start_sitl,
        start_copter,
        start_gradys_gs,
        kill_sitl_by_tag,
    )

    # Startup
    sitl_tag = start_sitl(args)
    copter = start_copter(args)

    drain_task = asyncio.create_task(copter.run_drain_mav_loop())
    gs_task, gs_session = await start_gradys_gs(args, copter)

    print("MCP server is ready.")

    # Run MCP server (blocks until shutdown)
    await mcp.run_streamable_http_async()

    # Shutdown
    print("Shutting down MCP server...")

    if sitl_tag is not None:
        print("Closing SITL and all associated windows...")
        kill_sitl_by_tag(sitl_tag)
        print("SITL and associated windows closed.")

    print("Cancelling Drain MAVLink loop...")
    drain_task.cancel()
    try:
        await drain_task
    except asyncio.CancelledError:
        print("Drain MAVLink loop has been cancelled.")

    if gs_task is not None:
        print("Cancelling Gradys GS location task...")
        gs_task.cancel()
        try:
            await gs_task
        except asyncio.CancelledError:
            print("Location task has been cancelled.")
        await gs_session.close()
        print("Gradys GS location task closed.")


def main():
    args = parse_args()
    args = setup(args)
    write_args_to_env(args)
    anyio.run(_run)


if __name__ == "__main__":
    main()
