import json
from typing import Any

from tests.utils import invoke_command

# TODO: test cancelling tasks? This is a fundamentally difficult thing to do as an integration
# test (which all of these are), because it requires you to set up some long-running task in
# pulp that you then swoop in and cancel before it finishes. I'd say don't bother unless we
# decide we need a unit test suite too.


def test_list(task: Any) -> None:
    result = invoke_command(["task", "list"])
    assert result.exit_code == 0
    response = json.loads(result.stdout)
    assert len(response) > 0


def test_list_with_ordering(task: Any, apt_repo: Any) -> None:
    result = invoke_command(["task", "list", "--ordering", "started_at"])
    assert result.exit_code == 0
    response = json.loads(result.stdout)
    assert len(response["results"]) > 1
    assert response["results"][-1]["started_at"] >= response["results"][0]["started_at"]

    result = invoke_command(["task", "list", "--ordering", "-started_at"])
    assert result.exit_code == 0
    response = json.loads(result.stdout)
    assert len(response) > 0
    assert response["results"][-1]["started_at"] <= response["results"][0]["started_at"]


def test_show(task: Any) -> None:
    result = invoke_command(["task", "show", task["id"]])
    assert result.exit_code == 0
    response = json.loads(result.stdout)
    assert task["id"] == response["id"]
