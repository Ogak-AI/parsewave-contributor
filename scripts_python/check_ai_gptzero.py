#!/usr/bin/env python3
"""
Script to check if task.yaml and solution.sh files are AI-generated using GPTZero API.

This script uses the GPTZero files endpoint to detect AI-generated content in:
- task.yaml instruction field
- solution.sh file

Usage:
    # Using API key from environment variable
    export GPTZERO_API_KEY="your-api-key"
    python scripts_python/check_ai_gptzero.py --task-id hello-world --tasks-dir tasks

    # Using API key as argument
    python scripts_python/check_ai_gptzero.py --task-id hello-world --api-key "your-api-key"

    # With custom output file
    python scripts_python/check_ai_gptzero.py --task-id my-task --output results.json

Requirements:
    pip install requests pyyaml

Get API key from: https://app.gptzero.me/app/api
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import yaml


class GPTZeroChecker:
    """Check if files contain AI-generated content using GPTZero API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        # Using cache proxy for cost optimization (original: https://api.gptzero.me/v2/predict)
        self.base_url = "https://admin.parsewave.ai/api/ai-check/gpt-zero/v2/predict"

    def check_files(self, files: Dict[str, str]) -> Dict[str, Any]:
        """
        Check multiple files for AI-generated content using GPTZero files endpoint.

        Args:
            files: Dictionary mapping filenames to file content

        Returns:
            dict with analysis results from GPTZero
        """
        headers = {
            "X-Api-Key": self.api_key,
        }

        # Prepare files for multipart/form-data upload
        files_data = []
        for filename, content in files.items():
            files_data.append(
                ('files', (filename, content, 'text/plain'))
            )

        try:
            response = requests.post(
                f"{self.base_url}/files",
                headers=headers,
                files=files_data,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error calling GPTZero API: {e}", file=sys.stderr)
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response status: {e.response.status_code}", file=sys.stderr)
                print(f"Response body: {e.response.text}", file=sys.stderr)
            return {
                "error": str(e),
                "documents": []
            }


def extract_instruction_from_yaml(yaml_path: Path) -> Optional[str]:
    """Extract the instruction field from task.yaml."""
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
            return data.get("instruction", "")
    except Exception as e:
        print(f"Error reading {yaml_path}: {e}", file=sys.stderr)
        return None


def analyze_task(task_id: str, tasks_dir: str, checker: GPTZeroChecker) -> Dict[str, Any]:
    """
    Analyze a task for AI-generated content.

    Args:
        task_id: Task identifier (e.g., "hello-world")
        tasks_dir: Root directory containing tasks (e.g., "tasks" or "our_tasks")
        checker: GPTZeroChecker instance

    Returns:
        dict with analysis results
    """
    task_path = Path(tasks_dir) / task_id

    if not task_path.exists():
        return {
            "task_id": task_id,
            "error": f"Task directory not found: {task_path}"
        }

    result = {
        "task_id": task_id,
        "task_path": str(task_path),
        "files_analyzed": [],
        "documents": []
    }

    # Prepare files to check
    files_to_check = {}

    # Extract instruction from task.yaml
    task_yaml_path = task_path / "task.yaml"
    if task_yaml_path.exists():
        instruction = extract_instruction_from_yaml(task_yaml_path)
        if instruction:
            files_to_check["task.yaml"] = instruction
            result["files_analyzed"].append("task.yaml (instruction field)")
        else:
            print(f"Warning: No instruction found in {task_yaml_path}", file=sys.stderr)
    else:
        print(f"Warning: task.yaml not found at {task_yaml_path}", file=sys.stderr)

    # Read solution.sh
    solution_path = task_path / "solution.sh"
    if solution_path.exists():
        try:
            with open(solution_path) as f:
                solution_content = f.read()
            files_to_check["solution.sh"] = solution_content
            result["files_analyzed"].append("solution.sh")
        except Exception as e:
            print(f"Error reading {solution_path}: {e}", file=sys.stderr)
    else:
        print(f"Warning: solution.sh not found at {solution_path}", file=sys.stderr)

    if not files_to_check:
        return {
            **result,
            "error": "No files found to analyze"
        }

    # Call GPTZero API
    print(f"Analyzing {len(files_to_check)} file(s) for task '{task_id}'...")
    api_response = checker.check_files(files_to_check)

    # Merge API response into result
    result["documents"] = api_response.get("documents", [])
    if "error" in api_response:
        result["error"] = api_response["error"]

    return result


def format_results(result: Dict[str, Any]) -> str:
    """Format analysis results for display."""
    output = []
    output.append("=" * 80)
    output.append(f"AI Detection Results: {result['task_id']}")
    output.append("=" * 80)

    if "error" in result:
        output.append(f"\nError: {result['error']}")
        return "\n".join(output)

    output.append(f"\nTask Path: {result['task_path']}")
    output.append(f"Files Analyzed: {', '.join(result['files_analyzed'])}")
    output.append("")

    documents = result.get("documents", [])
    if not documents:
        output.append("No results returned from GPTZero API")
        return "\n".join(output)

    # Map documents back to filenames
    filenames = list(result['files_analyzed'])

    for idx, doc in enumerate(documents):
        filename = filenames[idx] if idx < len(filenames) else "Unknown"
        output.append(f"\n{filename}:")
        output.append("-" * 40)

        # Overall metrics
        if "average_generated_prob" in doc:
            avg_prob = doc["average_generated_prob"]
            output.append(f"  Average AI Probability: {avg_prob:.2%}")

        if "completely_generated_prob" in doc:
            complete_prob = doc["completely_generated_prob"]
            output.append(f"  Completely Generated Probability: {complete_prob:.2%}")

        # Classification
        predicted_class = doc.get("predicted_class", "unknown")
        confidence_score = doc.get("confidence_score", 0)
        confidence_category = doc.get("confidence_category", "unknown")
        output.append(f"  Classification: {predicted_class}")
        output.append(f"  Confidence: {confidence_score:.2%} ({confidence_category})")

        # Result message from GPTZero
        if "result_message" in doc:
            output.append(f"  Result: {doc['result_message']}")

        # Sentence-level details (if available)
        sentences = doc.get("sentences", [])
        if sentences:
            output.append(f"\n  Sentence Analysis ({len(sentences)} sentences):")
            ai_sentences = [s for s in sentences if s.get("generated_prob", 0) > 0.5]
            if ai_sentences:
                output.append(f"    - {len(ai_sentences)} sentence(s) flagged as AI-generated")
                for i, sent in enumerate(ai_sentences[:3], 1):  # Show first 3
                    prob = sent.get("generated_prob", 0)
                    text = sent.get("sentence", "")[:60] + "..."
                    output.append(f"      {i}. [{prob:.2%}] {text}")
                if len(ai_sentences) > 3:
                    output.append(f"      ... and {len(ai_sentences) - 3} more")

    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description="Check if task files are AI-generated using GPTZero API"
    )
    parser.add_argument(
        "--task-id",
        required=True,
        help="Task identifier (e.g., hello-world)"
    )
    parser.add_argument(
        "--tasks-dir",
        default="tasks",
        help="Root directory containing tasks (default: tasks)"
    )
    parser.add_argument(
        "--api-key",
        help="GPTZero API key (default: read from GPTZERO_API_KEY env var)"
    )
    parser.add_argument(
        "--output",
        help="Output JSON file to save results (optional)"
    )
    parser.add_argument(
        "--short-output",
        action="store_true",
        help="Save only top-level document info (predicted_class, confidence, etc.) without nested objects"
    )

    args = parser.parse_args()

    # Get API key
    api_key = args.api_key or os.environ.get("GPTZERO_API_KEY")
    if not api_key:
        print("Error: GPTZero API key not provided", file=sys.stderr)
        print("Provide via --api-key argument or GPTZERO_API_KEY environment variable", file=sys.stderr)
        print("Get your API key from: https://app.gptzero.me/app/api", file=sys.stderr)
        sys.exit(1)

    # Initialize checker
    checker = GPTZeroChecker(api_key)

    # Analyze task
    result = analyze_task(args.task_id, args.tasks_dir, checker)

    # Save to file if requested
    if args.output:
        output_data = result

        # Create short output if requested
        if args.short_output:
            short_docs = []
            for doc in result.get("documents", []):
                short_doc = {
                    "predicted_class": doc.get("predicted_class"),
                    "confidence_score": doc.get("confidence_score"),
                    "confidence_category": doc.get("confidence_category"),
                    "average_generated_prob": doc.get("average_generated_prob"),
                    "completely_generated_prob": doc.get("completely_generated_prob"),
                    "document_classification": doc.get("document_classification"),
                    "result_message": doc.get("result_message"),
                    "language": doc.get("language"),
                    "version": doc.get("version")
                }
                short_docs.append(short_doc)

            output_data = {
                "task_id": result.get("task_id"),
                "task_path": result.get("task_path"),
                "files_analyzed": result.get("files_analyzed"),
                "documents": short_docs
            }

        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults saved to {args.output}")

    # Display results
    print("\n" + format_results(result))

    # Return exit code based on results
    if "error" in result:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
