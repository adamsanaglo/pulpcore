import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from pmc.schemas import Role
from tests.conftest import package_upload_command
from tests.utils import become, invoke_command

# Note that "package upload" is exercised by fixture.


PACKAGE_URL = "https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb"
FILE_URL = "https://packages.microsoft.com/keys/microsoft.asc"


def test_upload_file_type(orphan_cleanup: None) -> None:
    become(Role.Package_Admin)

    # file without file type
    path = Path.cwd() / "tests" / "assets" / "hello.txt"
    result = invoke_command(["package", "upload", str(path)])
    assert result.exit_code != 0
    assert "Could not determine package type" in result.stdout

    # python with file type
    path = Path.cwd() / "tests" / "assets" / "helloworld-0.0.1.tar.gz"
    result = invoke_command(["package", "upload", "--type", "python", str(path)])
    assert result.exit_code == 0


def _list_packages(type: str, filters: Optional[Dict[str, Any]] = None) -> Any:
    cmd = ["package", type, "list"]

    if filters:
        for key, val in filters.items():
            cmd.extend([f"--{key}", val])

    result = invoke_command(cmd)
    assert result.exit_code == 0
    response = json.loads(result.stdout)
    return response


def _assert_package_list_not_empty(type: str, filters: Optional[Dict[str, Any]] = None) -> None:
    response = _list_packages(type, filters)
    assert response["count"] > 0


def _assert_package_list_empty(type: str, filters: Optional[Dict[str, Any]] = None) -> None:
    response = _list_packages(type, filters)
    assert response["count"] == 0


def test_deb_list(deb_package: Any) -> None:
    _assert_package_list_not_empty("deb")
    _assert_package_list_not_empty("deb", {"name": deb_package["package"]})
    _assert_package_list_empty("deb", {"name": "helloworld"})
    _assert_package_list_not_empty("deb", {"version": deb_package["version"]})
    _assert_package_list_empty("deb", {"arch": "flux64"})


def test_rpm_list(rpm_package: Any) -> None:
    _assert_package_list_not_empty("rpm")
    _assert_package_list_not_empty("rpm", {"name": rpm_package["name"]})
    _assert_package_list_empty("rpm", {"name": "helloworld"})
    _assert_package_list_not_empty("rpm", {"version": rpm_package["version"]})
    _assert_package_list_empty("rpm", {"version": "0.0.0.0.0.0.0.0.1"})


def test_file_list(file_package: Any) -> None:
    _assert_package_list_not_empty("file")
    _assert_package_list_not_empty("file", {"relative-path": file_package["relative_path"]})
    _assert_package_list_empty("file", {"relative-path": "does/not/exist.exe"})


def test_python_list(python_package: Any) -> None:
    _assert_package_list_not_empty("python")
    _assert_package_list_not_empty("python", {"name": python_package["name"]})
    _assert_package_list_empty("python", {"name": "sneks"})
    _assert_package_list_not_empty("python", {"filename": python_package["filename"]})
    _assert_package_list_empty("python", {"filename": "sneks-0.0.1-py3-none-any.whl"})


def test_show(deb_package: Any) -> None:
    result = invoke_command(["package", "show", deb_package["id"]])
    assert result.exit_code == 0
    response = json.loads(result.stdout)
    assert deb_package["id"] == response["id"]


def test_zst_deb(zst_deb_package: Any) -> None:
    """This empty test ensures we handle zst packages correctly by exercising the fixture."""
    pass


@pytest.mark.parametrize("package", ["unsigned.deb", "unsigned.rpm", "signed-by-other.rpm"])
def test_unsigned_package(package: str) -> None:
    become(Role.Package_Admin)
    cmd = package_upload_command(package)
    result = invoke_command(cmd)
    assert result.exit_code != 0
    assert "UnsignedPackage" in result.stdout


def test_ignore_signature(forced_unsigned_package: Any) -> None:
    """This empty test ensures forcing an unsigned package works by exercising the fixture."""
    pass


def test_package_upload_by_url(orphan_cleanup: None) -> None:
    """Test a package upload by using a url."""
    become(Role.Package_Admin)
    result = invoke_command(["package", "upload", PACKAGE_URL])
    assert result.exit_code == 0

    result = invoke_command(["package", "upload", FILE_URL])
    assert result.exit_code == 1
    assert "Could not determine package type" in result.stdout

    result = invoke_command(["package", "upload", "--type", "file", FILE_URL])
    assert result.exit_code == 0
