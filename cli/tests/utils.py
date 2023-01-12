import json
import subprocess
from pathlib import Path
from random import choice
from typing import Any, Dict, List, Optional
from uuid import uuid4

from click.testing import Result
from typer.testing import CliRunner

from pmc.main import app, format_exception
from pmc.schemas import DistroType, RepoType, Role


def gen_repo_attrs(type: Optional[RepoType] = None) -> Dict[str, str]:
    if not type:
        type = choice([RepoType.apt, RepoType.yum, RepoType.python, RepoType.file])
    attrs = dict(name=f"pmc_cli_test_repo_{uuid4()}", type=type)
    if type in [RepoType.apt, RepoType.yum]:
        attrs["signing_service"] = "legacy"
    return attrs


def repo_create_cmd(attrs: Dict[str, str]) -> List[str]:
    cmd = [
        "repo",
        "create",
        attrs["name"],
        attrs["type"],
    ]
    if "signing_service" in attrs:
        cmd += [
            "--signing-service",
            attrs["signing_service"],
        ]
    return cmd


def gen_distro_attrs(pulp_type: DistroType = DistroType.apt) -> Dict[str, str]:
    return dict(
        name=f"pmc_cli_test_distro_{uuid4()}",
        type=pulp_type,
        base_path=f"{uuid4()}/{uuid4()}",
    )


def gen_release_attrs() -> Dict[str, str]:
    return dict(
        name=f"test_release_{uuid4()}",
        codename=f"test_release_{uuid4()}",
        suite="stable",
        components="main;contrib;non-free",
        architectures="arm;amd64",
    )


def gen_account_attrs() -> Dict[str, str]:
    my_uuid = str(uuid4())
    return dict(
        oid=my_uuid,
        name=f"pmc_cli_test_account_{my_uuid}",
        contact_email="alice@contoso.com;bob@contoso.com",
        icm_service="test_icm_service",
        icm_team="test_icm_team",
        role="Publisher",
    )


def account_create_command(**kwargs: str) -> List[str]:
    p = gen_account_attrs()
    p.update(kwargs)
    return [
        "account",
        "create",
        p["oid"],
        p["name"],
        p["contact_email"],
        p["icm_service"],
        p["icm_team"],
    ]


def invoke_command(*args: Any, **kwargs: Any) -> Result:
    """
    Invoke a command and handle any exception that gets thrown.

    CliRunner calls the command directly which bypasses the error handling in main's run() function.
    This function emulates the logic in run() by appending the formatted error dict to
    result.stdout_bytes.
    """
    if "runner" in kwargs:
        runner = kwargs.pop("runner")
    else:
        runner = CliRunner(mix_stderr=False)

    result: Result = runner.invoke(app, *args, **kwargs)
    if result.exception:
        err = format_exception(result.exception)
        result.stdout_bytes += json.dumps(err).encode("utf-8")
    return result


current_role = None


def become(role: Role) -> None:
    """Update our role in the database."""
    global current_role
    if current_role != role:
        subprocess.check_call([str(Path(__file__).parents[1] / "update_role.sh"), str(role)])
        current_role = role
