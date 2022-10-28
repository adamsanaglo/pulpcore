import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import typer
from click.exceptions import UsageError
from pydantic import AnyHttpUrl, ValidationError
from pydantic.tools import parse_obj_as

from .commands import access, account
from .commands import config as config_cmd
from .commands import distribution, orphan, package, remote, repository, task
from .commands.config import (
    BASE_URL_OPT,
    DEBUG_OPT,
    ID_ONLY_OPT,
    MSAL_AUTHORITY_OPT,
    MSAL_CERT_PATH_OPT,
    MSAL_CLIENT_ID_OPT,
    MSAL_SCOPE_OPT,
    MSAL_SNI_AUTH_OPT,
    NO_COLOR_OPT,
    NO_WAIT_OPT,
    RESP_FORMAT_OPT,
)
from .context import PMCContext
from .schemas import CONFIG_PATHS, Config, Format
from .utils import (
    DecodeError,
    PulpTaskFailure,
    UserFriendlyTyper,
    parse_config,
    resolve_config_path,
    validate_config,
)

app = UserFriendlyTyper()
app.add_typer(config_cmd.app, name="config")
app.add_typer(distribution.app, name="distro")
app.add_typer(remote.app, name="remote")
app.add_typer(package.app, name="package")
app.add_typer(repository.app, name="repo")
app.add_typer(task.app, name="task")
app.add_restricted_typer(account.app, name="account")
app.add_restricted_typer(access.app, name="access")
app.add_restricted_typer(orphan.app, name="orphan")


# Exceptions for which a traceback is not helpful/meaningful
NO_TRACEBACK_EXCEPTIONS = (httpx.HTTPStatusError, UsageError, ValidationError, DecodeError)


def _load_config(ctx: typer.Context, value: Optional[Path]) -> Optional[Path]:
    """Callback that attempts to load config."""
    path: Optional[Path] = None

    path = resolve_config_path(value)

    if path:
        try:
            config = parse_config(path)
            ctx.default_map = config.dict(exclude_unset=True)
        except Exception as e:
            # Ignore parse exceptions for now. validate later once we can exclude config subcommands
            typer.echo(f"Warning: Unable to parse config, using defaults: {e}", err=True)

    return path


def format_exception(exception: BaseException) -> Dict[str, Any]:
    """Build an error dict from an exception."""
    if isinstance(exception, httpx.HTTPStatusError) and exception.response.status_code == 401:
        return {
            "http_status": 401,
            "message": "Unauthorized, ensure that you have logged in by setting the msal options",
            "command_traceback": str(exception.request.url),
        }
    elif isinstance(exception, httpx.HTTPStatusError):
        err: Dict[str, Any] = {"message": str(exception)}

        try:
            resp_json = exception.response.json()
            err["detail"] = resp_json.get("detail")
        except (json.decoder.JSONDecodeError, AttributeError):
            if exception.response.text:
                err["detail"] = exception.response.text

        err["http_status"] = exception.response.status_code
        err["command_trackeback"] = str(exception.request.url)
        if "x-correlation-id" in exception.response.headers:
            err["correlation_id"] = exception.response.headers["x-correlation-id"]
    elif isinstance(exception, PulpTaskFailure):
        err = {
            "http_status": -1,
            "message": exception.original_message,
            "command_traceback": exception.original_traceback,
        }
        return err
    elif isinstance(exception, ValidationError):
        # config validation error
        err = {
            "http_status": -1,
            "message": "Missing or invalid option(s). See details for more info.",
            "detail": {err["loc"][0]: err["msg"] for err in exception.errors()},
        }
    else:
        exc_message = type(exception).__name__
        if message := str(exception):
            exc_message += f": {message}"

        err = {
            "http_status": -1,
            "message": exc_message,
            "detail": getattr(exception, "detail", None),
        }
        if isinstance(exception, httpx.RequestError):
            err["url"] = str(exception.request.url)

        if not isinstance(exception, NO_TRACEBACK_EXCEPTIONS):
            err["command_traceback"] = "".join(traceback.format_tb(exception.__traceback__))

    return err


@app.callback()
def main(
    ctx: typer.Context,
    config_path: Path = typer.Option(
        None,
        "--config",
        "-c",
        callback=_load_config,
        help="Config file location. Defaults: \n" + ("\n").join(map(str, CONFIG_PATHS)),
        envvar="PMC_CLI_CONFIG",
    ),
    no_wait: bool = NO_WAIT_OPT,
    no_color: bool = NO_COLOR_OPT,
    id_only: bool = ID_ONLY_OPT,
    debug: bool = DEBUG_OPT,
    resp_format: Format = RESP_FORMAT_OPT,
    base_url: str = BASE_URL_OPT,
    msal_client_id: str = MSAL_CLIENT_ID_OPT,
    msal_scope: str = MSAL_SCOPE_OPT,
    msal_cert_path: Path = MSAL_CERT_PATH_OPT,
    msal_SNIAuth: bool = MSAL_SNI_AUTH_OPT,
    msal_authority: str = MSAL_AUTHORITY_OPT,
) -> None:
    if ctx.invoked_subcommand == "config":
        # don't bother to validate the config or set up the context for config commands
        return

    if config_path:
        validate_config(config_path)
    else:
        typer.echo(
            "Warning: no config file. One can be generated with 'pmc config create'.", err=True
        )

    # New config options MUST be specified above and below in order to take effect!
    config = Config(
        no_wait=no_wait,
        no_color=no_color,
        id_only=id_only,
        debug=debug,
        resp_format=resp_format,
        msal_client_id=msal_client_id,  # pyright: ignore
        msal_scope=msal_scope,  # pyright: ignore
        msal_cert_path=msal_cert_path,
        msal_SNIAuth=msal_SNIAuth,
        msal_authority=msal_authority,  # pyright: ignore
    )
    if base_url:
        config.base_url = parse_obj_as(AnyHttpUrl, base_url)

    ctx.obj = PMCContext(config=config, config_path=config_path)

    if debug:
        typer.echo(f"Generated CID: {ctx.obj.cid.hex}")


def run() -> None:
    command = typer.main.get_command(app)

    try:
        command(standalone_mode=False)
    except Exception as exc:
        if not isinstance(exc, NO_TRACEBACK_EXCEPTIONS):
            traceback.print_exc()
        typer.echo("", err=True)

        err = format_exception(exc)
        if sys.stderr.isatty():
            output = json.dumps(err, indent=3)
        else:
            output = str(err)
        typer.echo(output, err=True)

        exit(1)
