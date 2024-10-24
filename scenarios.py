# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "typer",
#   "uv",
#   "niquests",
# ]
# ///

import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

import niquests
import typer

SCENARIOS_DIR = "scenarios"


def extract_filename(url: str) -> str:
    parsed_url = urlparse(url)
    path = unquote(parsed_url.path)
    return Path(path).name


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
        "pip-timemachine@0.2",
        date,
        "--port",
        port,
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        time.sleep(0.1)
        yield process
    finally:
        try:
            niquests.get(f"http://127.0.0.1:{port}/shutdown-pip-timemachine-server")
        except niquests.exceptions.ReadTimeout:
            pass
        
        process.wait()


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
            "--progress-bar",
            "off",
            "--disable-pip-version-check",
            "--index-url",
            f"http://127.0.0.1:{port}/simple",
            "--report",
            "-",
            *requirements,
        ]
        result_install = subprocess.run(command_install, capture_output=True, text=True)

    # Process output
    resolution_steps = []
    resolution_step = None
    report_lines = []
    report_output = False

    for line in result_install.stdout.splitlines():
        # Capture install report
        if line == "{":
            report_output = True
            report_lines.append(line)
            continue
        if report_output and line == "}":
            report_output = False
            report_lines.append(line)
            continue
        if report_output:
            report_lines.append(line)
            continue

        # Parse Logs
        unindented_line = line.strip()
        if unindented_line.startswith("Collecting"):
            if resolution_step:
                resolution_steps.append(resolution_step)

            resolution_step = {"requirement": unindented_line[11:], "packages": []}
            continue

        if resolution_step is None:
            continue

        if unindented_line.startswith("Using cached"):
            resolution_step["packages"].append(unindented_line[13:].split("(")[0].strip())
            continue

        if unindented_line.startswith("Downloading"):
            resolution_step["packages"].append(unindented_line[12:].split("(")[0].strip())
            continue

    if resolution_step:
        resolution_steps.append(resolution_step)

    # Clean last resolution step
    if resolution_steps:
        resolution_step = resolution_steps[-1]
        if resolution_step["packages"]:
            packages = resolution_step["packages"]
            if len(packages) > 1 and any(p.endswith(".metadata") for p in packages):
                resolution_steps[-1]["packages"] = [
                    p for p in packages if not p.endswith(".whl")
                ]

    # Grab install information from report
    install_info: list[dict[str, str]] = []
    if report_lines:
        report_json = json.loads("\n".join(report_lines))
        for report_install in report_json["install"]:
            download_info = report_install["download_info"]
            install_info.append(
                {
                    "file_name": extract_filename(download_info["url"]),
                    "hash": extract_filename(download_info["archive_info"]["hash"]),
                }
            )

    # Check success or failure reason
    success = True
    failure_reason = None
    stderr_lines = [
        line
        for line in result_install.stderr.splitlines()
        if line.strip() and not line.startswith("WARNING:")
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
            "install_info": sorted(
                install_info, key=lambda x: (x["file_name"], x["hash"])
            ),
        },
        "resolution": resolution_steps,
    }
    json.dump(output_json, json_path.open("w"), indent=4)


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
                    print(
                        f"Skipping previously completed (Pip Version: {pip_name}, Python: {python_version}, Date: {datetime})"
                    )
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
