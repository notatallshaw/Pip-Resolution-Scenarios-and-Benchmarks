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
        max_resolution_rounds: int | None = scenario.get("max_resolution_rounds")
        constraints: list[str] | None = scenario.get("constraints")

        json_path_1 = (
            Path("summaries")
            / os.path.splitext(toml_file.name)[0]
            / scenario_name
            / f"{pip_name_1}.json"
        )
        json_path_2 = (
            Path("summaries")
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
                "max_resolution_rounds": max_resolution_rounds,
                "constraints": constraints,
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
                "max_resolution_rounds": max_resolution_rounds,
                "constraints": constraints,
            }
        ):
            print(f"Warning: JSON 2 not in sync with TOML scenario: {str(json_path_1)}")
            continue

        success_1 = json_1["result"]["success"]
        success_2 = json_2["result"]["success"]
        failure_reason_1 = json_1["result"]["failure_reason"]
        failure_reason_2 = json_2["result"]["failure_reason"]
        install_info_1 = {
            install.get("file", install.get("url")): install.get("hash", install.get("commit"))
            for install in json_1["summary"]["install_info"]
        }
        install_info_2 = {
            install.get("file", install.get("url")): install.get("hash", install.get("commit"))
            for install in json_2["summary"]["install_info"]
        }

        # Use pre-calculated summary metrics
        summary_1 = json_1["summary"]
        summary_2 = json_2["summary"]
        
        wheels_1 = summary_1["distinct_wheels_visited"]
        sdists_1 = summary_1["distinct_sdists_visited"]
        visited_packages_1 = summary_1["total_visited_packages"]
        visited_requirements_1 = summary_1["total_visited_requirements"]
        rejected_rquirements_1 = summary_1["total_rejected_requirements"]
        number_pinned_1 = summary_1["total_pinned_packages"]
        number_rounds_1 = summary_1["total_rounds"]

        wheels_2 = summary_2["distinct_wheels_visited"]
        sdists_2 = summary_2["distinct_sdists_visited"]
        visited_packages_2 = summary_2["total_visited_packages"]
        visited_requirements_2 = summary_2["total_visited_requirements"]
        rejected_rquirements_2 = summary_2["total_rejected_requirements"]
        number_pinned_2 = summary_2["total_pinned_packages"]
        number_rounds_2 = summary_2["total_rounds"]

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

        if (wheels_1 != wheels_2 or sdists_1 != sdists_2 or 
            visited_packages_1 != visited_packages_2 or visited_requirements_1 != visited_requirements_2 or
            rejected_rquirements_1 != rejected_rquirements_2 or number_pinned_1 != number_pinned_2 or
            number_rounds_1 != number_rounds_2):
            
            if sdists_1 != sdists_2:
                difference_messages.append(
                    f"Distinct Sdists visisted: {sdists_1} -> {sdists_2} ({percent_change(sdists_1, sdists_2)})"
                )

            if wheels_1 != wheels_2:
                difference_messages.append(
                    f"Distinct Wheels visisted: {wheels_1} -> {wheels_2} ({percent_change(wheels_1, wheels_2)})"
                )

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
