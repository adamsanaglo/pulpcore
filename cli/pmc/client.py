import json
import shutil
from contextlib import contextmanager
from time import sleep
from typing import Any, Callable, Generator, List, Optional, Union

import click
import httpx
import typer

from .context import PMCContext
from .schemas import FINISHED_TASK_STATES

try:
    from pygments import highlight, styles
    from pygments.formatters import Terminal256Formatter
    from pygments.lexers import JsonLexer
except ImportError:
    PYGMENTS = False
else:
    PYGMENTS = True
    if "solarized-light" in styles.STYLE_MAP.keys():
        PYGMENTS_STYLE = "solarized-light"
    else:
        # old versions of pygments (< 2.4.0) don't have solarized
        PYGMENTS_STYLE = "native"


TaskHandler = Optional[Callable[[str], Any]]


def _set_auth_header(ctx: PMCContext, request: httpx.Request) -> None:
    try:
        token = ctx.auth.acquire_token()
    except Exception:
        typer.echo("Failed to retrieve AAD token", err=True)
        raise
    request.headers["Authorization"] = f"Bearer {token}"


def _log_request(request: httpx.Request) -> None:
    typer.echo(f"Request: {request.method} {request.url}")

    if "content-type" in request.headers and request.headers["content-type"] == "application/json":
        typer.echo(f"Body: {json.loads(request.content)}")


def _log_response(response: httpx.Response) -> None:
    request = response.request
    typer.echo(f"Response: {request.method} {request.url} - Status {response.status_code}")


def _raise_for_status(response: httpx.Response) -> None:
    response.read()  # read the response's body before raise_for_status closes it
    response.raise_for_status()


@contextmanager
def get_client(ctx: PMCContext) -> Generator[httpx.Client, None, None]:
    def _call_set_auth_header(request: httpx.Request) -> None:
        _set_auth_header(ctx, request)

    request_hooks = [_call_set_auth_header]
    response_hooks = [_raise_for_status]

    if ctx.config.debug:
        request_hooks.append(_log_request)
        response_hooks.insert(0, _log_response)

    client = httpx.Client(
        base_url=ctx.config.base_url,
        event_hooks={"request": request_hooks, "response": response_hooks},
        headers={"x-correlation-id": ctx.cid.hex},
        timeout=None,
    )
    try:
        yield client
    finally:
        client.close()


def _extract_ids(resp_json: Any) -> Union[str, List[str], None]:
    if not isinstance(resp_json, dict):
        return None
    elif id := resp_json.get("id"):
        return str(id)
    elif task_id := resp_json.get("task"):
        return str(task_id)
    elif results := resp_json.get("results"):
        return [r["id"] for r in results]
    else:
        return None


def poll_task(ctx: PMCContext, task_id: str, task_handler: TaskHandler = None) -> Any:
    with get_client(ctx) as client:
        resp = client.get(f"/tasks/{task_id}/")
        # While waiting for long tasks, we occasionally encounter an issue where our auth token
        # expires /right after/ we make a request and we get a 401. In that case let's simply try
        # again one extra time, which should trigger a re-auth and work.
        if resp.status_code == httpx.codes.UNAUTHORIZED:
            resp = client.get(f"/tasks/{task_id}/")

        if ctx.config.no_wait:
            return resp

        task = resp.json()
        typer.echo(f"Waiting for {task['id']}...", nl=False, err=True)

        while task["state"] not in FINISHED_TASK_STATES:
            sleep(1)
            resp = client.get(f"/tasks/{task['id']}/")
            task = resp.json()
            typer.echo(".", err=True, nl=False)

    typer.echo("", err=True)

    if task_handler:
        resp = task_handler(task)
    else:
        typer.echo("Done.", err=True)

    return resp


def handle_response(
    ctx: PMCContext, resp: httpx.Response, task_handler: TaskHandler = None
) -> None:
    if not resp.content:
        # empty response
        return

    if isinstance(resp.json(), dict) and (task_id := resp.json().get("task")):
        resp = poll_task(ctx, task_id, task_handler)

    if ctx.config.id_only and (id := _extract_ids(resp.json())):
        typer.echo(id, nl=ctx.isatty)
    else:
        output = json.dumps(resp.json(), indent=3)
        if PYGMENTS and not ctx.config.no_color:
            formatter = Terminal256Formatter(style=PYGMENTS_STYLE)
            output = highlight(output, JsonLexer(), formatter)
        if (
            ctx.config.pager
            and not task_id  # don't show pager for polled task
            and output.count("\n") > shutil.get_terminal_size().lines - 3
        ):
            click.echo_via_pager(output)
        else:
            typer.echo(output)
