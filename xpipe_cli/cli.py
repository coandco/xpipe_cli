from typing import Optional

import click
from xpipe_client import Client
from prettytable import PrettyTable
from tqdm import tqdm


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


@cli.command()
@click.argument('remote', type=str)
@click.argument('local', type=click.File('wb'))
@click.pass_obj
def pull(client: Client, remote: str, local: click.File):
    """Read REMOTE (<connection_name>:/path/to/file) and write to LOCAL (/path/to/file)"""
    connection, remote_path = remote.rsplit(":", 1)
    connection = resolve_connection_name(client, connection)
    client.shell_start(connection)
    try:
        stat_result = client.shell_exec(connection, f'stat -c %s {remote_path}')
        length = int(stat_result["stdout"])
    except Exception:
        length = 0
    with tqdm(total=length, unit="B", unit_scale=True) as progress_bar:
        resp = client._fs_read(connection, remote_path)
        length = int(resp.headers.get("content-length", 0))
        progress_bar.total = length
        progress_bar.refresh()
        for chunk in resp.iter_content(1024):
            progress_bar.update(len(chunk))
            local.write(chunk)
    client.shell_stop(connection)


@cli.command()
@click.argument('local', type=click.File('rb'))
@click.argument('remote', type=str)
@click.pass_obj
def push(client: Client, local: click.File, remote: str):
    """Read LOCAL (/path/to/file) and write to REMOTE (<connection_name>:/path/to/file)"""
    connection, remote_path = remote.rsplit(":", 1)
    connection = resolve_connection_name(client, connection)
    client.shell_start(connection)
    client.shell_stop(connection)

@cli.command()
@click.argument('connection', type=str)
@click.argument('command', type=str)
@click.pass_obj
def exec(client: Client, connection: str, command: str):
    """Execute COMMAND on CONNECTION"""
    pass


if __name__ == '__main__':
    cli()
