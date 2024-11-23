# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "compact_json",
#   "inflection",
#   "typer",
#   "uv",
#   "niquests",
# ]
# ///

import ast
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import defaultdict
from contextlib import contextmanager
from io import TextIOWrapper
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import inflection
import niquests
import typer
from compact_json import EolStyle, Formatter

SCENARIOS_DIR = "scenarios"


def extract_filename(url: str) -> str:
    # Remove text in parentheses
    url_no_suffix = re.sub(r"\s*\(.*?\)", "", url)

    # Parse the URL and get the last part of the path
    parsed_url = urlparse(url_no_suffix)
    filename = Path(parsed_url.path).name
    return filename


def snakecase_and_strip_suffix(input_str, suffix="_requirement"):
    # Convert to snake_case
    snake_case_str = inflection.underscore(input_str)
    # Remove the suffix if it exists at the end
    if snake_case_str.endswith(suffix):
        snake_case_str = snake_case_str[: -len(suffix)]
    return snake_case_str


class PinningVisitor(ast.NodeVisitor):
    def __init__(self):
        self.pinned_file = None

    def visit_Call(self, node):
        # Check if the function is Reporter.pinning
        if isinstance(node.func, ast.Attribute) and node.func.attr == "pinning":
            if node.args:
                # Check for nested ExtrasCandidate
                first_arg = node.args[0]
                if (
                    isinstance(first_arg, ast.Call)
                    and first_arg.func.id == "ExtrasCandidate"
                ):
                    self.handle_extras_candidate(first_arg)
                # Direct LinkCandidate usage
                elif (
                    isinstance(first_arg, ast.Call)
                    and first_arg.func.id == "LinkCandidate"
                ):
                    self.extract_linkcandidate_filename(first_arg)

        self.generic_visit(node)

    def handle_extras_candidate(self, extras_candidate_node):
        # Check the base argument within ExtrasCandidate
        for keyword in extras_candidate_node.keywords:
            if keyword.arg == "base" and isinstance(keyword.value, ast.Call):
                if keyword.value.func.id == "LinkCandidate":
                    self.extract_linkcandidate_filename(keyword.value)

    def extract_linkcandidate_filename(self, link_candidate_node):
        # Extract the filename from LinkCandidate URL argument
        if link_candidate_node.args and isinstance(
            link_candidate_node.args[0], ast.Constant
        ):
            self.pinned_file = extract_filename(link_candidate_node.args[0].value)


class RejectedAddedVisitor(ast.NodeVisitor):
    def __init__(self):
        self.candidates = []

    def visit_Call(self, node):
        # Check for "rejecting_candidate" and traverse its arguments
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "rejecting_candidate":
                # Find `Criterion` in the arguments
                for arg in node.args:
                    if (
                        isinstance(arg, ast.Call)
                        and isinstance(arg.func, ast.Name)
                        and arg.func.id == "Criterion"
                    ):
                        self.process_criterion(arg)
            elif node.func.attr == "adding_requirement":
                if len(node.args) == 2:
                    self.extract_requirement_via_pair(node.args[0], node.args[1])

        self.generic_visit(node)

    def process_criterion(self, criterion_node):
        for item in criterion_node.args:
            if isinstance(item, ast.Tuple) and len(item.elts) >= 2:
                requirement, via = item.elts
                self.extract_requirement_via_pair(requirement, via)

    def extract_requirement_via_pair(self, requirement_node, via_node):
        requirement_text = None
        via_filename = None

        # Check if requirement_node is a SpecifierRequirement with a string argument
        if isinstance(requirement_node, ast.Call) and requirement_node.func.id.endswith(
            "Requirement"
        ):
            if requirement_node.args:
                if isinstance(requirement_node.args[0], ast.Constant):
                    requirement_text = requirement_node.args[0].value
                elif (
                    isinstance(requirement_node.args[0], ast.Call)
                    and requirement_node.args[0].func.id == "LinkCandidate"
                ):
                    requirement_text = extract_filename(
                        requirement_node.args[0].args[0].value
                    )

        # Check if ExtrasCandidate and extract LinkCandidate from it
        if isinstance(via_node, ast.Call) and via_node.func.id == "ExtrasCandidate":
            if (
                via_node.keywords
                and via_node.keywords[0].value.func.id == "LinkCandidate"
            ):
                via_node = via_node.keywords[0].value

        # Check if link_candidate_node is a LinkCandidate with a URL argument
        if isinstance(via_node, ast.Call) and via_node.func.id == "LinkCandidate":
            if via_node.args and isinstance(via_node.args[0], ast.Constant):
                via_filename = extract_filename(via_node.args[0].value)

        if isinstance(via_node, ast.Constant) and via_node.value is None:
            via_filename = "<User Requirement>"

        # Append to the list if both requirement and via data are present
        if requirement_text and via_filename:
            self.candidates.append(
                {"requirement": requirement_text, "from": via_filename}
            )


def get_open_port() -> int:
    _sockeet = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _sockeet.bind(("", 0))
    address = _sockeet.getsockname()
    port = address[1]
    _sockeet.close()
    return port


@contextmanager
def pip_timemachine(date: str, port: str):
    cmd = [
        sys.executable,
        "-m",
        "uv",
        "tool",
        "run",
        "-p",
        "3.12",
        "pip-timemachine@0.2.2",
        date,
        "--port",
        port,
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # Wait for server to come up before yielding process
        for _ in range(100):
            try:
                niquests.get(
                    f"http://127.0.0.1:{port}/simple/pip",
                    headers={"Accept": "application/vnd.pypi.simple.v1+json"},
                )
            except niquests.exceptions.ConnectionError:
                time.sleep(0.1)
            else:
                break
        else:
            raise RuntimeError("Failed to start pip-timemachine")

        yield process
    finally:
        # Request shutdown but don't wait on process
        try:
            niquests.get(f"http://127.0.0.1:{port}/shutdown-pip-timemachine-server")
        except niquests.exceptions.ReadTimeout:
            pass


class ReporterLines:
    def __init__(self) -> None:
        self._report_output = False
        self.reporter_lines: list[str] = []

    def process_line(self, line) -> None:
        if line == "{":
            self._report_output = True
            self.reporter_lines.append(line)
            return

        if self._report_output and line == "}":
            self._report_output = False
            self.reporter_lines.append(line)
            return

        if self._report_output:
            self.reporter_lines.append(line)
            return


class ResolutionLines:
    def __init__(self) -> None:
        self._resolution_step: dict[str, Any] = {}
        self.resolution_rounds: list[dict[str, Any]] = []

    def process_line(self, line: str):
        if not line.startswith("Reporter."):
            return

        if line.startswith("Reporter.starting("):
            return

        if line.startswith("Reporter.starting_round("):
            self._resolution_step = {}
            return

        if line.startswith("Reporter.ending_round"):
            if self._resolution_step:
                if "rejected" in self._resolution_step:
                    for requirement, froms in self._resolution_step["rejected"].items():
                        self._resolution_step["rejected"][requirement] = sorted(froms)
                self.resolution_rounds.append(self._resolution_step)
            return

        if line.startswith("Reporter.ending("):
            return

        if line.startswith("Reporter.adding_requirement("):
            tree = ast.parse(line, mode="eval")
            requirements_visistor = RejectedAddedVisitor()
            requirements_visistor.visit(tree)
            if len(requirements_visistor.candidates) == 1:
                if "added" not in self._resolution_step:
                    self._resolution_step["added"] = defaultdict(list)

                self._resolution_step["added"][
                    requirements_visistor.candidates[0]["from"]
                ].append(requirements_visistor.candidates[0]["requirement"])
            else:
                raise ValueError(f"Unknown requirement {line}")
            return

        if line.startswith("Reporter.pinning("):
            if "RequiresPythonCandidate" in line:
                self._resolution_step["pinned"] = "PythonCandidate"
                return

            tree = ast.parse(line, mode="eval")
            pinning_visistor = PinningVisitor()
            pinning_visistor.visit(tree)
            if pinning_visistor.pinned_file:
                if "pinned" in self._resolution_step:
                    raise ValueError(f"Unexpected second pinning: {line}")
                self._resolution_step["pinned"] = pinning_visistor.pinned_file
            else:
                raise ValueError(f"Unknown pinning {line}")
            return

        if line.startswith("Reporter.rejecting_candidate("):
            rejecting_visistor = RejectedAddedVisitor()
            try:
                tree = ast.parse(line.replace("via=", ""), mode="eval")
            except Exception:
                breakpoint()
                "break"
            rejecting_visistor.visit(tree)
            if rejecting_visistor.candidates:
                if "rejected" not in self._resolution_step:
                    self._resolution_step["rejected"] = defaultdict(set)

                for candidate in rejecting_visistor.candidates:
                    self._resolution_step["rejected"][candidate["requirement"]].add(
                        candidate["from"]
                    )
            else:
                raise ValueError(f"Unknown rejection {line}")
            return

        raise ValueError(f"Unknown Report action: {line}")


def tail_file(file: TextIOWrapper):
    partial_line = ""
    while True:
        line = file.readline()
        if line:
            if line.endswith("\n"):
                partial_line = ""
                yield partial_line + line.rstrip("\n")
            else:
                partial_line += line
                yield None
        else:
            yield None


def process_scenario(
    pip_name: str,
    pip_requirement: str,
    python_version: str,
    platform_system: str,
    requirements: list[str],
    datetime: str,
    json_path: Path,
):
    port = str(get_open_port())
    with pip_timemachine(datetime, port), tempfile.TemporaryDirectory() as temp_dir:
        # Create a virtual environment
        venv_dir = Path(temp_dir) / ".venv"
        create_venv_cmd = ["uv", "venv", "--python", python_version, str(venv_dir)]
        result_create_venv = subprocess.run(
            create_venv_cmd, capture_output=True, text=True
        )

        if result_create_venv.returncode != 0:
            print(f"Error creating venv: {result_create_venv.stderr}")
            return

        # Determine the path to the Python executable in the virtual environment
        venv_python = (
            venv_dir / "bin" / "python"
            if os.name != "nt"
            else venv_dir / "Scripts" / "python.exe"
        )

        # Install the version of pip you are testing
        install_pip_cmd = [
            sys.executable,
            "-m",
            "uv",
            "pip",
            "install",
            "--python",
            str(venv_python),
            pip_requirement,
        ]
        result_install_pip = subprocess.run(
            install_pip_cmd, capture_output=True, text=True
        )

        if result_install_pip.returncode != 0:
            print(f"Error creating venv: {result_create_venv.stderr}")
            return

        # Install the requirements
        command_install = [
            str(venv_python),
            "-W",
            "ignore",
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--progress-bar",
            "off",
            "--disable-pip-version-check",
            "--index-url",
            f"http://127.0.0.1:{port}/simple",
            "--report",
            "-",
            *requirements,
        ]

        # Write the process output to temporary files and then tail from
        # those temporary files as it runs, this some big advantages:
        #  * The output is not in memory (it can get massive)
        #  * We can process the output as it runs
        #  * We can terminate early if there are too many rounds
        stdout_path = os.path.join(temp_dir, "stdout.txt")
        stderr_path = os.path.join(temp_dir, "stderr.txt")
        stderr_lines: list[str] = []
        report_lines = ReporterLines()
        resolution_lines = ResolutionLines()
        resolution_too_deep = False
        with open(stdout_path, "w") as out, open(stderr_path, "w") as err:
            process = subprocess.Popen(
                command_install,
                stdout=out,
                stderr=err,
                text=True,
                env={"PIP_RESOLVER_DEBUG": "1", **os.environ},
            )
            with (
                open(stdout_path, "r") as stdout_tail,
                open(stderr_path, "r") as stderr_tail,
            ):
                stdout_gen = tail_file(stdout_tail)
                stderr_gen = tail_file(stderr_tail)

                while process.poll() is None and resolution_too_deep is False:
                    stdout_line = next(stdout_gen, None)
                    if stdout_line:
                        resolution_lines.process_line(stdout_line)
                        report_lines.process_line(stdout_line)

                        # End early if there are too many resolution rounds
                        if len(resolution_lines.resolution_rounds) >= 15_000:
                            resolution_too_deep = True
                            try:
                                process.terminate()
                                process.wait(5)
                            except subprocess.TimeoutExpired:
                                process.kill()

                            continue

                    stderr_line = next(stderr_gen, None)
                    if stderr_line:
                        if stderr_line:
                            stderr_lines.append(stderr_line)

                    if stdout_line is None and stderr_line is None:
                        time.sleep(0.1)

                # Consume any remaining lines in the file
                for stdout_line in stdout_gen:
                    if stdout_line:
                        resolution_lines.process_line(stdout_line)
                        report_lines.process_line(stdout_line)
                    else:
                        break

                for stderr_line in stderr_gen:
                    if stderr_line:
                        stderr_lines.append(stderr_line)
                    else:
                        break

    # Grab install information from report
    install_info: list[dict[str, str]] = []
    if report_lines.reporter_lines:
        report_json = json.loads("\n".join(report_lines.reporter_lines))
        for report_install in report_json["install"]:
            download_info = report_install["download_info"]
            install_info.append(
                {
                    "file": extract_filename(download_info["url"]),
                    "hash": extract_filename(download_info["archive_info"]["hash"]),
                }
            )

    # Check success or failure reason
    success = True
    failure_reason = None
    stderr_lines = [
        line for line in stderr_lines if line.strip() and not line.startswith("WARNING:")
    ]

    # Clear metadata warning lines from stderr
    stderr_clean = []
    metadata_warning = False
    for stderr_line in stderr_lines:
        if "has invalid metadata" in stderr_line:
            metadata_warning = True
            continue
        if not metadata_warning:
            stderr_clean.append(stderr_line)
        if "nPlease use pip<24.1" in stderr_line:
            metadata_warning = False

    stderr = "\n".join(stderr_clean)
    if stderr:
        success = False
        if "subprocess-exited-with-error" in stderr:
            failure_reason = "Build Failure"
        elif "ResolutionTooDeep" in stderr:
            failure_reason = "Resolution Too Deep"
        elif "ResolutionImpossible" in stderr:
            failure_reason = "Resolution Impossible"
        else:
            failure_reason = stderr

    if resolution_too_deep:
        success = False
        failure_reason = "Resolution Too Deep"

    # Build and dump JSON
    output_json = {
        "input": {
            "pip_version": pip_name,
            "python_version": python_version,
            "datetime": datetime,
            "platform_system": platform_system,
            "requirements": requirements,
        },
        "result": {
            "success": success,
            "failure_reason": failure_reason,
            "install_info": sorted(install_info, key=lambda x: (x["file"], x["hash"])),
        },
        "resolution_rounds": resolution_lines.resolution_rounds,
    }
    formatter = Formatter()
    formatter.indent_spaces = 1
    formatter.max_inline_complexity = 1
    formatter.max_inline_length = 10_000
    formatter.nested_bracket_padding = False
    formatter.simple_bracket_padding = False
    formatter.table_dict_minimum_similarity = 101
    formatter.table_list_minimum_similarity = 101
    formatter.json_eol_style = EolStyle.LF

    formatter.dump(output_json, output_file=str(json_path), newline_at_eof=True)


def process_toml_file(toml_file: Path, pip_name: str, pip_requirement: str) -> None:
    local_platform_system = platform.system()

    print(f"Running scenarios for system platform: {local_platform_system}")
    with open(toml_file, "rb") as f:
        scenarios = tomllib.load(f)

    for scenario_name, scenario in scenarios.items():
        python_version: str = scenario["python_version"]
        platform_system: str = scenario["platform_system"]
        datetime: str = scenario["datetime"]
        requirements: list[str] = scenario["requirements"]

        if platform_system != local_platform_system:
            continue

        json_path = (
            Path("output")
            / os.path.splitext(toml_file.name)[0]
            / scenario_name
            / f"{pip_name}.json"
        )
        if json_path.exists():
            try:
                existing_json = json.load(json_path.open())
            except json.JSONDecodeError:
                os.remove(json_path)
                json_path.touch()
            else:
                existing_input = existing_json["input"]
                if existing_input == (
                    {
                        "pip_version": pip_name,
                        "python_version": python_version,
                        "datetime": datetime,
                        "platform_system": platform_system,
                        "requirements": requirements,
                    }
                ):
                    continue
        else:
            json_path.parent.mkdir(exist_ok=True, parents=True)
            json_path.touch()

        print(
            f"Processing {scenario_name!r}: (Pip Version: {pip_name}, Python: {python_version}, Date: {datetime})"
        )
        process_scenario(
            pip_name=pip_name,
            pip_requirement=pip_requirement,
            datetime=datetime,
            python_version=python_version,
            platform_system=platform_system,
            requirements=requirements,
            json_path=json_path,
        )


def main(
    pip_version: str | None = None,
    github_repo: str | None = None,
    git_commit: str | None = None,
) -> None:
    """
    Pass in either a pip version or a github branch and git commit
    """
    pip_requirement = None
    if pip_version:
        pip_name = pip_version
        pip_requirement = f"pip=={pip_version}"
    elif github_repo and git_commit:
        pip_name = f"{github_repo.replace('/', '#')}@{git_commit}"
        pip_requirement = f"pip @ git+https://github.com/{github_repo}.git@{git_commit}"
    else:
        raise RuntimeError(
            "Provide either a pip version or a github branch and git commit"
        )

    scenarios_path = Path(SCENARIOS_DIR)
    if not scenarios_path.exists() or not scenarios_path.is_dir():
        print(f"The directory '{SCENARIOS_DIR}' does not exist.")
        return

    # Loop through each TOML file in the scenarios directory
    for toml_file in scenarios_path.glob("*.toml"):
        print(f"\n--- Processing file: {toml_file.name[:-5]} ---")
        process_toml_file(
            toml_file=toml_file, pip_name=pip_name, pip_requirement=pip_requirement
        )


if __name__ == "__main__":
    typer.run(main)
