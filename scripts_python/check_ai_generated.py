#!/usr/bin/env python3
"""
Script to check if task.yaml and solution.sh files are AI-generated using Copyleaks API.

All results are always saved to a JSON file (default: ai_detection_results.json).

Usage:
    python scripts_python/check_ai_generated.py
    python scripts_python/check_ai_generated.py --task-dir our_tasks/path-tracing
    python scripts_python/check_ai_generated.py --output results.json
    python scripts_python/check_ai_generated.py --credentials-file /path/to/.credentials.yaml

Requirements:
    pip install requests pyyaml
"""

import argparse
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import requests
import yaml


class CopyleaksChecker:
    """Check if text is AI-generated using Copyleaks API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.copyleaks.com/v2/writer-detector"
        self.auth_url = "https://id.copyleaks.com/v3/account/login/api"
        self.access_token = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate with Copyleaks API to get access token."""
        try:
            # Copyleaks API key format is typically "email|key"
            # If the key doesn't contain a pipe, assume it's just the key
            if "|" in self.api_key:
                email, key = self.api_key.split("|", 1)
            else:
                # If no email provided, use a placeholder - update as needed
                raise ValueError(
                    "COPYLEAKS_KEY must be in format 'email|key'. "
                    "Get your API key from https://copyleaks.com/"
                )

            payload = {"email": email, "key": key}
            response = requests.post(self.auth_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            self.access_token = data.get("access_token")

            if not self.access_token:
                raise ValueError("Failed to obtain access token from Copyleaks")

        except requests.exceptions.RequestException as e:
            print(f"Error authenticating with Copyleaks API: {e}")
            raise

    def check_text(self, text: str) -> dict[str, Any]:
        """
        Check if text is AI-generated.

        Args:
            text: The text to analyze

        Returns:
            dict with analysis results including:
                - is_ai_generated: bool
                - ai_probability: float (0-1)
                - ai_score: float (0-100)
                - human_score: float (0-100)
        """
        scan_id = str(uuid.uuid4())
        endpoint = f"{self.base_url}/{scan_id}/check"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        payload = {"text": text}

        try:
            response = requests.post(
                endpoint, headers=headers, json=payload, timeout=30
            )
            response.raise_for_status()
            data = response.json()

            # Extract relevant fields from Copyleaks response
            # Copyleaks returns summary with ai, human, and mixed scores
            summary = data.get("summary", {})
            ai_score = summary.get("ai", 0)
            human_score = summary.get("human", 0)

            return {
                "ai_probability": ai_score / 100.0,  # Convert to 0-1 range
                "ai_score": ai_score,
                "human_score": human_score,
                "mixed_score": summary.get("mixed", 0),
                "raw_response": data,
            }
        except requests.exceptions.RequestException as e:
            print(f"Error calling Copyleaks API: {e}")
            return {
                "error": str(e),
                "ai_probability": None,
            }

    def check_file(self, file_path: str) -> dict[str, Any]:
        """
        Check if a file's content is AI-generated.

        Args:
            file_path: Path to the file

        Returns:
            dict with analysis results
        """
        try:
            with open(file_path) as f:
                content = f.read()
            return self.check_text(content)
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return {
                "error": str(e),
                "ai_probability": None,
            }


def extract_instruction_from_yaml(yaml_path: str) -> str:
    """Extract the instruction field from task.yaml."""
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
            return data.get("instruction", "")
    except Exception as e:
        print(f"Error reading {yaml_path}: {e}")
        return ""


def find_all_tasks(tasks_dir: str = "our_tasks") -> list[Path]:
    """Find all task directories containing task.yaml."""
    tasks_path = Path(tasks_dir)
    return [p.parent for p in tasks_path.glob("*/task.yaml")]


def analyze_task(task_dir: Path, checker: CopyleaksChecker, rate_limit_delay: float = 1.0) -> dict[str, Any]:
    """
    Analyze a single task directory.

    Args:
        task_dir: Path to task directory
        checker: CopyleaksChecker instance
        rate_limit_delay: Delay between API calls in seconds

    Returns:
        dict with analysis results
    """
    result = {
        "task_name": task_dir.name,
        "task_yaml": None,
        "solution_sh": None,
    }

    # Check task.yaml instruction
    task_yaml_path = task_dir / "task.yaml"
    if task_yaml_path.exists():
        instruction = extract_instruction_from_yaml(str(task_yaml_path))
        if instruction:
            print(f"Analyzing task.yaml instruction for {task_dir.name}...")
            result["task_yaml"] = checker.check_text(instruction)
            result["task_yaml"]["instruction_preview"] = instruction[:200] + "..."
            time.sleep(rate_limit_delay)  # Rate limiting

    # Check solution.sh
    solution_path = task_dir / "solution.sh"
    if solution_path.exists():
        print(f"Analyzing solution.sh for {task_dir.name}...")
        with open(solution_path) as f:
            solution_content = f.read()
        result["solution_sh"] = checker.check_text(solution_content)
        result["solution_sh"]["content_preview"] = solution_content[:200] + "..."
        time.sleep(rate_limit_delay)  # Rate limiting

    return result


def load_credentials(credentials_file: str = ".credentials.yaml") -> dict[str, str]:
    """Load credentials from YAML file."""
    try:
        with open(credentials_file) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"Error: Credentials file '{credentials_file}' not found")
        print("Please create it with COPYLEAKS_KEY: email|key")
        raise
    except Exception as e:
        print(f"Error loading credentials file: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Check if task.yaml and solution.sh files are AI-generated using Copyleaks"
    )
    parser.add_argument(
        "--credentials-file",
        default=".credentials.yaml",
        help="Path to credentials YAML file (default: .credentials.yaml)",
    )
    parser.add_argument(
        "--task-id",
        help="Specific task ID to analyze (e.g., path-tracing)",
    )
    parser.add_argument(
        "--task-dir",
        help="Specific task directory to analyze (e.g., tasks/path-tracing)",
    )
    parser.add_argument(
        "--tasks-root",
        default="our_tasks",
        help="Root directory containing all tasks (default: tasks)",
    )
    parser.add_argument(
        "--output",
        default="ai_detection_results.json",
        help="Output JSON file to save results (default: ai_detection_results.json)",
    )
    parser.add_argument(
        "--rate-limit-delay",
        type=float,
        default=1.0,
        help="Delay between API calls in seconds (default: 1.0)",
    )

    args = parser.parse_args()

    # Load credentials
    credentials = load_credentials(args.credentials_file)
    api_key = credentials.get("COPYLEAKS_KEY")

    if not api_key:
        print("Error: COPYLEAKS_KEY not found in credentials file")
        print("Please add COPYLEAKS_KEY: email|key to your credentials file")
        print("Get your API key from https://copyleaks.com/")
        return

    # Initialize checker
    checker = CopyleaksChecker(api_key)

    # Get tasks to analyze
    if args.task_id:
        task_path = Path(args.tasks_root) / args.task_id
        if not task_path.exists():
            print(f"Error: Task directory not found: {task_path}")
            return
        tasks = [task_path]
        print(f"Analyzing task: {args.task_id}")
    elif args.task_dir:
        tasks = [Path(args.task_dir)]
        print(f"Analyzing task directory: {args.task_dir}")
    else:
        tasks = find_all_tasks(args.tasks_root)
        print(f"Found {len(tasks)} tasks to analyze")

    # Analyze tasks
    results = []
    for task_dir in tasks:
        try:
            result = analyze_task(task_dir, checker, args.rate_limit_delay)
            results.append(result)
        except Exception as e:
            print(f"Error analyzing {task_dir}: {e}")
            results.append(
                {
                    "task_name": task_dir.name,
                    "error": str(e),
                }
            )

    # Generate summary
    summary = {
        "total_tasks": len(results),
        "tasks_analyzed": len([r for r in results if not r.get("error")]),
    }

    # Create output
    output = {
        "summary": summary,
        "results": results,
    }

    # Always save results to file
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to {args.output}")
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(json.dumps(summary, indent=2))

    # Print detailed summary for single task analysis
    if args.task_id or args.task_dir:
        if results and not results[0].get("error"):
            result = results[0]
            print("\n" + "=" * 80)
            print(f"DETAILED RESULTS: {result['task_name']}")
            print("=" * 80)

            # Task YAML results
            if result.get("task_yaml"):
                task_yaml = result["task_yaml"]
                print("\nTask YAML (instruction field):")
                print("-" * 40)
                if "error" in task_yaml:
                    print(f"  Error: {task_yaml['error']}")
                else:
                    print(f"  AI Score: {task_yaml.get('ai_score', 'N/A')}%")
                    print(f"  Human Score: {task_yaml.get('human_score', 'N/A')}%")
                    print(f"  Mixed Score: {task_yaml.get('mixed_score', 'N/A')}%")
                    print(f"  AI Probability: {task_yaml.get('ai_probability', 'N/A')}")
            else:
                print("\nTask YAML: Not analyzed")

            # Solution.sh results
            if result.get("solution_sh"):
                solution = result["solution_sh"]
                print("\nSolution.sh:")
                print("-" * 40)
                if "error" in solution:
                    print(f"  Error: {solution['error']}")
                else:
                    print(f"  AI Score: {solution.get('ai_score', 'N/A')}%")
                    print(f"  Human Score: {solution.get('human_score', 'N/A')}%")
                    print(f"  Mixed Score: {solution.get('mixed_score', 'N/A')}%")
                    print(f"  AI Probability: {solution.get('ai_probability', 'N/A')}")
            else:
                print("\nSolution.sh: Not analyzed")
        elif results and results[0].get("error"):
            print(f"\nError analyzing task: {results[0]['error']}")

    print("\nDone!")


if __name__ == "__main__":
    main()
