# xpipe_cli
[![GitHub license](https://img.shields.io/github/license/coandco/xpipe_cli.svg)](https://github.com/coandco/xpipe_cli/blob/master/LICENSE)
[![PyPI version](https://img.shields.io/pypi/v/xpipe_cli)](https://pypi.org/project/xpipe_cli/)

CLI that takes advantage of the new XPipe 10 API

## Installation
Using pipx to install xpipe_cli in its own virtualenv is highly recommended.
```commandline
python3 -m pip install pipx
python3 -m pipx install xpipe_cli
```

## Usage examples

```commandline
# See available actions
xpipe-cli --help

# List connections while filtering on the name
xpipe-cli ls --name 'shell environments/*'

# Probe connections (make sure they're connectable and get os info) using same filters
xpipe-cli probe --name 'shell environments/*'

# Run a local script file on a remote host
xpipe-cli run-script localfile.sh name-of-remote-host

# Execute a command on a remote host
xpipe-cli exec 'echo hello world' name-of-remote-host

# Pull a file from a remote host
xpipe-cli pull name-of-remote-host:/path/to/file localfile

# Push a file to a remote host
xpipe-cli push localfile name-of-remote-host:/path/to/file
```

All places where xpipe-cli accepts a local filename, it will also accept `-` to read directly from stdin.
