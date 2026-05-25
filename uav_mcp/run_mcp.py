import anyio

from uav_mcp.args import parse_args, write_args_to_env


async def _run():
    from uav_mcp.mcp_app import mcp, wait_for_uav_api, base_url
    from uav_mcp import uav_api_client

    url = base_url()
    try:
        await wait_for_uav_api(url)
        await uav_api_client.init(url)

        print("MCP server is ready.")
        await mcp.run_streamable_http_async()
    finally:
        print("Shutting down MCP server...")
        try:
            await uav_api_client.close()
        except BaseException:
            pass


def main():
    args = parse_args()
    write_args_to_env(args)

    from uav_mcp.mcp_app import start_uav_api, kill_uav_api_by_tag

    api_tag = start_uav_api()
    try:
        anyio.run(_run)
    except KeyboardInterrupt:
        print("UAV MCP terminated by user.")
    finally:
        if api_tag is not None:
            print(f"Killing spawned uav-api (tag={api_tag})...")
            kill_uav_api_by_tag(api_tag)


if __name__ == "__main__":
    main()
