import json
from typing import Optional, List

import click
from prettytable import PrettyTable
from tqdm import tqdm
from xpipe_client import Client, AsyncClient
import asyncio


# Resolving to shortest name length for now, probably want to throw an error on duplicates once testing is done
def resolve_connection_name(client: Client, name: str) -> Optional[str]:
    # Special-case the local/default connection
    if name == "":
        return client.connection_query(connections="")[0]["connection"]
    all_connections = client.connection_query()
    possible_matches = sorted([x for x in all_connections if x["name"] and x["name"][-1] == name], key=lambda x: len(x["name"]))
    return possible_matches[0]["connection"] if possible_matches else None


@click.group()
@click.option('--ptb', is_flag=True, help="Use PTB port instead of release port")
@click.option('--base-url', default=None, help="Override the URL of the XPipe server to talk to")
@click.option("--token", default=None, help="The API token to use if the XPipe server isn't local")
@click.pass_context
def cli(ctx: click.Context, ptb: bool, base_url: Optional[str], token: Optional[str]):
    ctx.obj = Client(token=token, base_url=base_url, ptb=ptb)


@cli.command()
@click.option('--category', '-c', default='*', help='Globbed category filter, defaults to *')
@click.option('--name', '-n', default='*', help="Globbed name filter, defaults to *")
@click.option('--type', default='*', help="Globbed type filter, defaults to *")
@click.option('--output-format', '-f', default="text", type=click.Choice(["text", "html", "json", "csv", "latex"]), help="Output format")
@click.option('--sort-by', default="name", type=click.Choice(['name', 'type', 'category', 'uuid'], case_sensitive=False), help="Field to sort by")
@click.option('--reverse', is_flag=True, help="Sort the table in reverse")
@click.pass_obj
def ls(client: Client, category: str, name: str, type: str, output_format: str, sort_by: str, reverse: bool):
    """Lists connections, with optional filters"""
    connections = client.connection_query(categories=category, connections=name, types=type)
    table = PrettyTable()
    table.align = 'l'
    table.field_names = ["Name", "Type", "Category", "UUID"]
    for c in connections:
        table.add_row(["/".join(c["name"]), c["type"], ",".join(c["category"]), c["connection"]])
    print(table.get_formatted_string(output_format, sortby=sort_by.title(), reversesort=reverse))


async def probe_connections(async_client: AsyncClient, connections: List[dict]) -> List[Exception]:
    await async_client.renew_session()
    lock = asyncio.Semaphore(10)

    async def _probe(connection) -> dict:
        async with lock:
            try:
                return await async_client.shell_start(connection["connection"])
            except Exception as e:
                print(f"Connection '{'/'.join(connection['name'])}' failed with error {e}")
                raise

    async def _close(connection):
        async with lock:
            await async_client.shell_stop(connection["connection"])

    async def _progress(tasks: List[asyncio.Task]):
        while num_left := len([x for x in tasks if not x.done()]):
            print(f"{num_left} hosts remaining...")
            await asyncio.sleep(5)

    tasks = [asyncio.create_task(_probe(x)) for x in connections]
    progress_task = asyncio.create_task(_progress(tasks))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    await progress_task
    await asyncio.gather(*(asyncio.create_task(_close(x)) for x in connections), return_exceptions=True)
    # If we have no exceptions, we were successful
    return all(isinstance(x, dict) for x in results)


@cli.command()
@click.option('--category', '-c', default='*', help='Globbed category filter, defaults to *')
@click.option('--name', '-n', default='*', help="Globbed name filter, defaults to *")
@click.option('--type', default='*', help="Globbed type filter, defaults to *")
@click.pass_obj
def probe(client: Client, category: str, name: str, type: str):
    connections = client.connection_query(categories=category, connections=name, types=type)
    print(f"Spinning up probe requests for {len(connections)} hosts...")
    async_client = AsyncClient.from_sync_client(client)
    success = asyncio.run(probe_connections(async_client, connections))
    print("Probing finished with no errors!" if success else "Some errors during probing")


@cli.command()
@click.argument('remote', type=str)
@click.argument('local', type=click.File('wb'))
@click.pass_obj
def pull(client: Client, remote: str, local: click.File):
    """Read REMOTE (<connection_name>:/path/to/file) and write to LOCAL (/path/to/file)"""
    connection_name, remote_path = remote.rsplit(":", 1)
    connection = resolve_connection_name(client, connection_name)
    if not connection:
        print(f"Couldn't find connection UUID for {connection_name}")
        exit(1)
    client.shell_start(connection)
    print(f"Getting size of remote file {remote}...")
    try:
        stat_result = client.shell_exec(connection, f'stat -c %s {remote_path}')
        length = int(stat_result["stdout"])
    except Exception:
        length = 0
    print(f"Copying {remote} to {local.name}...")
    with tqdm(total=length, unit="B", unit_scale=True) as progress_bar:
        resp = client._fs_read(connection, remote_path)
        length = int(resp.headers.get("content-length", 0))
        progress_bar.total = length
        progress_bar.refresh()
        for chunk in resp.iter_content(1024):
            progress_bar.update(len(chunk))
            local.write(chunk)
    print(f"Done!")
    client.shell_stop(connection)


@cli.command()
@click.argument('local', type=click.File('rb'))
@click.argument('remote', type=str)
@click.pass_obj
def push(client: Client, local: click.File, remote: str):
    """Read LOCAL (/path/to/file) and write to REMOTE (<connection_name>:/path/to/file)"""
    connection_name, remote_path = remote.rsplit(":", 1)
    connection = resolve_connection_name(client, connection_name)
    if not connection:
        print(f"Couldn't find connection UUID for {connection_name}")
        exit(1)
    client.shell_start(connection)
    print(f"Uploading {local.name} to XPipe API...")
    blob_id = client.fs_blob(local)
    print(f"Copying uploaded file to {remote}...")
    client.fs_write(connection, blob_id, remote_path)
    client.shell_stop(connection)
    print("Done!")


@cli.command(name='exec')
@click.argument('connection_name', type=str)
@click.argument('command', type=str)
@click.option('-r', '--raw', is_flag=True, help="Print stdout directly instead of the whole result object")
@click.pass_obj
def fs_exec(client: Client, connection_name: str, command: str, raw: bool):
    """Execute COMMAND on CONNECTION_NAME"""
    connection = resolve_connection_name(client, connection_name)
    if not connection:
        print(f"Couldn't find connection UUID for {connection_name}")
        exit(1)
    client.shell_start(connection)
    result = client.shell_exec(connection, command)
    if raw:
        print(result["stdout"])
    else:
        print(json.dumps(result, indent=2))
    client.shell_stop(connection)

@cli.command()
@click.argument('connection_name', type=str)
@click.argument('script_file', type=click.File('rb'))
@click.option('-r', '--raw', is_flag=True, help="Print stdout directly instead of the whole result object")
@click.pass_obj
def run_script(client: Client, connection_name, script_file: click.File, raw: bool):
    connection = resolve_connection_name(client, connection_name)
    if not connection:
        print(f"Couldn't find connection UUID for {connection_name}")
        exit(1)
    client.shell_start(connection)
    blob_id = client.fs_blob(script_file)
    remote_path = client.fs_script(connection, blob_id)
    result = client.shell_exec(connection, remote_path)
    if raw:
        print(result["stdout"])
    else:
        print(json.dumps(result, indent=2))
    client.shell_stop(connection)


if __name__ == '__main__':
    cli()
