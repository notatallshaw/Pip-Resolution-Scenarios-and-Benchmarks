# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "typer",
# ]
# ///

import json
import os
import tomllib
from collections import defaultdict
from pathlib import Path

import typer

SCENARIOS_DIR = "scenarios"


def process_toml_file(toml_file: Path, pip_name_1: str, pip_name_2: str) -> None:
    with open(toml_file, "rb") as f:
        scenarios = tomllib.load(f)

    for scenario_name, scenario in scenarios.items():
        python_version: str = scenario["python_version"]
        platform_system: str = scenario["platform_system"]
        datetime: str = scenario["datetime"]
        requirements: list[str] = scenario["requirements"]

        json_path_1 = (
            Path("output")
            / os.path.splitext(toml_file.name)[0]
            / scenario_name
            / f"{pip_name_1}.json"
        )
        json_path_2 = (
            Path("output")
            / os.path.splitext(toml_file.name)[0]
            / scenario_name
            / f"{pip_name_2}.json"
        )
        if not json_path_1.exists():
            continue
        if not json_path_2.exists():
            continue

        json_1 = json.load(json_path_1.open())
        input_1 = json_1["input"]
        if input_1 != (
            {
                "pip_version": pip_name_1,
                "python_version": python_version,
                "datetime": datetime,
                "platform_system": platform_system,
                "requirements": requirements,
            }
        ):
            print(f"Warning: JSON 1 not in sync with TOML scenario: {str(json_path_1)}")
            continue

        json_2 = json.load(json_path_2.open())
        input_2 = json_2["input"]
        if input_2 != (
            {
                "pip_version": pip_name_2,
                "python_version": python_version,
                "datetime": datetime,
                "platform_system": platform_system,
                "requirements": requirements,
            }
        ):
            print(f"Warning: JSON 2 not in sync with TOML scenario: {str(json_path_1)}")
            continue

        success_1 = json_1["result"]["success"]
        success_2 = json_2["result"]["success"]
        failure_reason_1 = json_1["result"]["failure_reason"]
        failure_reason_2 = json_2["result"]["failure_reason"]
        install_info_1 = {
            install["file_name"]: install["hash"]
            for install in json_1["result"]["install_info"]
        }
        install_info_2 = {
            install["file_name"]: install["hash"]
            for install in json_2["result"]["install_info"]
        }

        resolution_1 = defaultdict(list)
        for resolution_step in json_1["resolution"]:
            resolution_1[resolution_step["requirement"]].extend(
                resolution_step["packages"]
            )

        resolution_2 = defaultdict(list)
        for resolution_step in json_2["resolution"]:
            resolution_2[resolution_step["requirement"]].extend(
                resolution_step["packages"]
            )

        difference_messages = []
        one_failed = success_1 != success_2
        if one_failed:
            difference_messages.append(f"Success: {success_1} -> {success_2}.")

        if failure_reason_1 != failure_reason_2:
            difference_messages.append(
                f"Failure Reason: {failure_reason_1} -> {failure_reason_2}."
            )
    
        if not one_failed and install_info_1 != install_info_2:
            difference_messages.append("Not the same install files.")

        if resolution_1 != resolution_2:
            num_requirements_1 = len(resolution_1.keys())
            num_requirements_2 = len(resolution_2.keys())
            if num_requirements_1 != num_requirements_2:
                difference_messages.append(
                    f"Number of requirements processed: {num_requirements_1} -> {num_requirements_2}"
                )

            num_packages_1 = sum(len(x) for x in resolution_1.values())
            num_packages_2 = sum(len(x) for x in resolution_2.values())
            if num_packages_1 != num_packages_2:
                difference_messages.append(
                    f"Number of packages processed: {num_packages_1} -> {num_packages_2}"
                )

        if difference_messages:
            print(f"Difference for scenario {toml_file} - {scenario_name}:")
            print("\n".join(f"\t{d}" for d in difference_messages))
            print()


def main(
    pip_version_1: str | None = None,
    github_repo_1: str | None = None,
    git_commit_1: str | None = None,
    pip_version_2: str | None = None,
    github_repo_2: str | None = None,
    git_commit_2: str | None = None,
) -> None:
    """
    Pass in either a pip version or a github branch and git commit
    """
    if pip_version_1:
        pip_name_1 = pip_version_1
    elif github_repo_1 and git_commit_1:
        pip_name_1 = f"{github_repo_1.replace('/', '#')}@{git_commit_1}"
    else:
        raise RuntimeError(
            "Provide either a pip version or a github branch and git commit"
        )

    if pip_version_2:
        pip_name_2 = pip_version_2
    elif github_repo_2 and git_commit_2:
        pip_name_2 = f"{github_repo_2.replace('/', '#')}@{git_commit_2}"
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
        process_toml_file(
            toml_file=toml_file, pip_name_1=pip_name_1, pip_name_2=pip_name_2
        )


if __name__ == "__main__":
    typer.run(main)
