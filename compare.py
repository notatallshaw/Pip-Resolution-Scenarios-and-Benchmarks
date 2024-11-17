# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "typer",
# ]
# ///

import json
import os
import tomllib
from pathlib import Path

import typer

SCENARIOS_DIR = "scenarios"


def percent_change(value_1: int, value_2: int) -> str:
    if value_1 == 0:
        if value_2 == 0:
            return "100%"
        else:
            return "inf%"

    return f"{(value_2 * 100)/value_1:.2f}%"


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
            install["file"]: install["hash"]
            for install in json_1["result"]["install_info"]
        }
        install_info_2 = {
            install["file"]: install["hash"]
            for install in json_2["result"]["install_info"]
        }

        wheels_1: set[str] = set()
        sdists_1: set[str] = set()
        visited_packages_1 = 0
        visited_requirements_1 = 0
        rejected_rquirements_1 = 0
        number_pinned_1 = 0
        number_rounds_1 = len(json_1["resolution_rounds"])
        for resolution_round_1 in json_1["resolution_rounds"]:
            if "pinned" in resolution_round_1:
                number_pinned_1 += 1
            if "added" in resolution_round_1:
                visited_packages_1 += len(resolution_round_1["added"])
                wheels_1.update(
                    w for w in resolution_round_1["added"] if w.endswith(".whl")
                )
                sdists_1.update(
                    s for s in resolution_round_1["added"] if not s.endswith(".whl")
                )
                for added_requirements_1 in resolution_round_1["added"].values():
                    visited_requirements_1 += len(added_requirements_1)
            if "rejected" in resolution_round_1:
                rejected_rquirements_1 += len(resolution_round_1["rejected"])

        wheels_2: set[str] = set()
        sdists_2: set[str] = set()
        visited_packages_2 = 0
        visited_requirements_2 = 0
        rejected_rquirements_2 = 0
        number_pinned_2 = 0
        number_rounds_2 = len(json_2["resolution_rounds"])
        for resolution_round_2 in json_2["resolution_rounds"]:
            if "pinned" in resolution_round_2:
                number_pinned_2 += 1
            if "added" in resolution_round_2:
                visited_packages_2 += len(resolution_round_2["added"])
                wheels_2.update(
                    w for w in resolution_round_2["added"] if w.endswith(".whl")
                )
                sdists_2.update(
                    s for s in resolution_round_2["added"] if not s.endswith(".whl")
                )
                for added_requirements_2 in resolution_round_2["added"].values():
                    visited_requirements_2 += len(added_requirements_2)
            if "rejected" in resolution_round_2:
                rejected_rquirements_2 += len(resolution_round_2["rejected"])

        difference_messages = []
        one_failed = success_1 != success_2
        if one_failed:
            difference_messages.append(f"Success: {success_1} -> {success_2}")

        if failure_reason_1 != failure_reason_2:
            difference_messages.append(
                f"Failure Reason: {failure_reason_1} -> {failure_reason_2}"
            )
        elif failure_reason_1 and failure_reason_1 == failure_reason_2:
            difference_messages.append(f"Both failed: {failure_reason_1}")

        if not one_failed and install_info_1 != install_info_2:
            difference_messages.append("Not the same install files")

        if json_1["resolution_rounds"] != json_2["resolution_rounds"]:
            if len(sdists_1) != len(sdists_2):
                difference_messages.append(
                    f"Distinct Sdists visisted: {len(sdists_1)} -> {len(sdists_2)} ({percent_change(len(sdists_1), len(sdists_2))})"
                )
            elif len(sdists_1) != len(sdists_2):
                difference_messages.append("Different distinct sdists visisted")

            if len(wheels_1) != len(wheels_2):
                difference_messages.append(
                    f"Distinct Wheels visisted: {len(wheels_1)} -> {len(wheels_2)} ({percent_change(len(wheels_1), len(wheels_2))})"
                )
            elif len(wheels_1) != len(wheels_2):
                difference_messages.append("Different distinct wheels visisted")

            if visited_packages_1 != visited_packages_2:
                difference_messages.append(
                    f"Total visisted packages: {visited_packages_1} -> {visited_packages_2} ({percent_change(visited_packages_1, visited_packages_2)})"
                )

            if visited_requirements_1 != visited_requirements_2:
                difference_messages.append(
                    f"Total visisted requirements: {visited_requirements_1} -> {visited_requirements_2} ({percent_change(visited_requirements_1, visited_requirements_2)})"
                )

            if rejected_rquirements_1 != rejected_rquirements_2:
                difference_messages.append(
                    f"Total rejected requirements: {rejected_rquirements_1} -> {rejected_rquirements_2} ({percent_change(rejected_rquirements_1, rejected_rquirements_2)})"
                )

            if number_pinned_1 != number_pinned_2:
                difference_messages.append(
                    f"Total pinned packages: {number_pinned_1} -> {number_pinned_2} ({percent_change(number_pinned_1, number_pinned_2)})"
                )

            if number_rounds_1 != number_rounds_2:
                difference_messages.append(
                    f"Total rounds: {number_rounds_1} -> {number_rounds_2} ({percent_change(number_rounds_1, number_rounds_2)})"
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
        print(f"The directory '{SCENARIOS_DIR}' does not exist")
        return

    # Loop through each TOML file in the scenarios directory
    for toml_file in scenarios_path.glob("*.toml"):
        process_toml_file(
            toml_file=toml_file, pip_name_1=pip_name_1, pip_name_2=pip_name_2
        )


if __name__ == "__main__":
    typer.run(main)
