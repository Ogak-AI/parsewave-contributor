#!/usr/bin/env python3
"""
Detect similar tasks between tasks/ and our_tasks/ folders.

This script analyzes task.yaml files to find potentially duplicate or highly similar tasks
using multiple similarity metrics:
- Text similarity (TF-IDF + cosine similarity)
- Structural similarity (file paths, metadata)
- Fuzzy string matching

Usage:
    # Compare all tasks against each other
    python detect_similar_tasks.py [--threshold 0.75] [--output report.txt]

    # Compare a specific task against all existing tasks
    python detect_similar_tasks.py --check-task /path/to/task-dir [--threshold 0.75]
"""

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from difflib import SequenceMatcher
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class Task:
    """Represents a task with its metadata."""
    task_id: str
    folder: str  # 'tasks' or 'our_tasks'
    instruction: str
    category: str
    difficulty: str
    tags: list[str]
    input_files: list[str]
    output_files: list[str]
    yaml_path: Path


def extract_file_paths(instruction: str) -> tuple[list[str], list[str]]:
    """Extract file paths mentioned in instruction text."""
    import re

    # Match patterns like /app/file.txt, /path/to/file, etc.
    # Updated to handle spaces, brackets, and more special characters
    # Matches absolute paths and relative paths with ./
    file_pattern = r'(?:\.)?/[\w\-./\[\]\(\) ]+'
    paths = re.findall(file_pattern, instruction)

    # Heuristic: paths with common output indicators
    output_indicators = ['output', 'result', 'report', 'summary']

    input_files = []
    output_files = []

    for path in paths:
        lower_path = path.lower()
        if any(indicator in lower_path for indicator in output_indicators):
            output_files.append(path)
        else:
            input_files.append(path)

    return input_files, output_files


def load_task(yaml_path: Path, folder: str) -> Task | None:
    """Load a task from its task.yaml file."""
    try:
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)

        if not data or 'instruction' not in data:
            return None

        instruction = data['instruction']

        # Validate instruction is not None or empty
        if not instruction or not instruction.strip():
            return None
        task_id = yaml_path.parent.name

        input_files, output_files = extract_file_paths(instruction)

        return Task(
            task_id=task_id,
            folder=folder,
            instruction=instruction,
            category=data.get('category', ''),
            difficulty=data.get('difficulty', ''),
            tags=data.get('tags', []),
            input_files=input_files,
            output_files=output_files,
            yaml_path=yaml_path
        )
    except Exception as e:
        print(f"Error loading {yaml_path}: {e}", file=sys.stderr)
        return None


def load_all_tasks(base_path: Path) -> list[Task]:
    """Load all tasks from both tasks/ and our_tasks/ folders."""
    tasks = []

    for folder in ['tasks', 'our_tasks']:
        folder_path = base_path / folder
        if not folder_path.exists():
            print(f"Warning: {folder_path} does not exist", file=sys.stderr)
            continue

        for task_yaml in folder_path.glob('*/task.yaml'):
            task = load_task(task_yaml, folder)
            if task:
                tasks.append(task)

    return tasks


def calculate_text_similarity(tasks: list[Task]) -> dict[tuple[int, int], float]:
    """Calculate TF-IDF cosine similarity between all task instructions."""
    if len(tasks) < 2:
        return {}

    instructions = [task.instruction for task in tasks]

    # Validate all instructions are non-empty
    if not all(inst.strip() for inst in instructions):
        print("Warning: Some tasks have empty instructions", file=sys.stderr)

    # Create TF-IDF vectors
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words='english',
        ngram_range=(1, 2),  # Use unigrams and bigrams
        max_features=1000
    )

    try:
        tfidf_matrix = vectorizer.fit_transform(instructions)
    except ValueError as e:
        print(f"Warning: TF-IDF vectorization failed: {e}", file=sys.stderr)
        # Return zero similarity for all pairs if vectorization fails
        similarities = {}
        for i in range(len(tasks)):
            for j in range(i + 1, len(tasks)):
                similarities[(i, j)] = 0.0
        return similarities

    # Calculate cosine similarity
    similarity_matrix = cosine_similarity(tfidf_matrix)

    # Store pairwise similarities
    similarities = {}
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            similarities[(i, j)] = similarity_matrix[i, j]

    return similarities


def calculate_fuzzy_similarity(text1: str, text2: str) -> float:
    """Calculate fuzzy string similarity using SequenceMatcher."""
    import re

    # Normalize text: lowercase, collapse whitespace, remove extra punctuation
    def normalize(text: str) -> str:
        # Lowercase
        text = text.lower()
        # Normalize whitespace (collapse multiple spaces/tabs/newlines to single space)
        text = re.sub(r'\s+', ' ', text)
        # Strip leading/trailing whitespace
        text = text.strip()
        return text

    norm1 = normalize(text1)
    norm2 = normalize(text2)

    return SequenceMatcher(None, norm1, norm2).ratio()


def calculate_structural_similarity(task1: Task, task2: Task) -> float:
    """Calculate structural similarity based on metadata and file paths."""
    score = 0.0
    weights = {
        'category': 0.2,
        'difficulty': 0.1,
        'tags': 0.2,
        'input_files': 0.25,
        'output_files': 0.25
    }

    # Category match (case-insensitive, strip whitespace)
    if task1.category and task2.category:
        if task1.category.strip().lower() == task2.category.strip().lower():
            score += weights['category']

    # Difficulty match (case-insensitive, strip whitespace)
    if task1.difficulty and task2.difficulty:
        if task1.difficulty.strip().lower() == task2.difficulty.strip().lower():
            score += weights['difficulty']

    # Tag overlap (case-insensitive)
    if task1.tags and task2.tags:
        tags1 = set(tag.strip().lower() for tag in task1.tags)
        tags2 = set(tag.strip().lower() for tag in task2.tags)
        if tags1 and tags2:  # Both must be non-empty for meaningful comparison
            jaccard = len(tags1 & tags2) / len(tags1 | tags2)
            score += weights['tags'] * jaccard

    # Input file overlap (normalize paths)
    if task1.input_files and task2.input_files:
        # Normalize paths: strip, handle // and /./
        def normalize_path(p: str) -> str:
            from pathlib import Path
            try:
                return str(Path(p).as_posix())
            except:
                return p.strip()

        files1 = set(normalize_path(f) for f in task1.input_files)
        files2 = set(normalize_path(f) for f in task2.input_files)
        if files1 and files2:  # Both must be non-empty for meaningful comparison
            jaccard = len(files1 & files2) / len(files1 | files2)
            score += weights['input_files'] * jaccard

    # Output file overlap (normalize paths)
    if task1.output_files and task2.output_files:
        def normalize_path(p: str) -> str:
            from pathlib import Path
            try:
                return str(Path(p).as_posix())
            except:
                return p.strip()

        files1 = set(normalize_path(f) for f in task1.output_files)
        files2 = set(normalize_path(f) for f in task2.output_files)
        if files1 and files2:  # Both must be non-empty for meaningful comparison
            jaccard = len(files1 & files2) / len(files1 | files2)
            score += weights['output_files'] * jaccard

    return score


@dataclass
class SimilarityResult:
    """Represents a similarity comparison between two tasks."""
    task1: Task
    task2: Task
    text_similarity: float
    fuzzy_similarity: float
    structural_similarity: float
    combined_score: float

    def __str__(self) -> str:
        # Only add ellipsis if instruction is longer than 200 chars
        inst1_preview = self.task1.instruction[:200]
        inst1_suffix = "..." if len(self.task1.instruction) > 200 else ""
        inst2_preview = self.task2.instruction[:200]
        inst2_suffix = "..." if len(self.task2.instruction) > 200 else ""

        return (
            f"\n{'='*80}\n"
            f"Task 1: {self.task1.folder}/{self.task1.task_id}\n"
            f"Task 2: {self.task2.folder}/{self.task2.task_id}\n"
            f"{'-'*80}\n"
            f"Text Similarity (TF-IDF):     {self.text_similarity:.3f}\n"
            f"Fuzzy String Similarity:      {self.fuzzy_similarity:.3f}\n"
            f"Structural Similarity:        {self.structural_similarity:.3f}\n"
            f"Combined Score:               {self.combined_score:.3f}\n"
            f"{'-'*80}\n"
            f"Category: {self.task1.category} vs {self.task2.category}\n"
            f"Difficulty: {self.task1.difficulty} vs {self.task2.difficulty}\n"
            f"Tags: {self.task1.tags} vs {self.task2.tags}\n"
            f"Input files: {self.task1.input_files} vs {self.task2.input_files}\n"
            f"Output files: {self.task1.output_files} vs {self.task2.output_files}\n"
            f"{'-'*80}\n"
            f"Instruction 1:\n{inst1_preview}{inst1_suffix}\n"
            f"{'-'*80}\n"
            f"Instruction 2:\n{inst2_preview}{inst2_suffix}\n"
        )


def find_similar_tasks(tasks: list[Task], threshold: float = 0.75) -> list[SimilarityResult]:
    """Find all pairs of similar tasks above the threshold."""
    # Calculate text similarities
    text_similarities = calculate_text_similarity(tasks)

    results = []

    for (i, j), text_sim in text_similarities.items():
        task1, task2 = tasks[i], tasks[j]

        # Calculate other similarities
        fuzzy_sim = calculate_fuzzy_similarity(task1.instruction, task2.instruction)
        struct_sim = calculate_structural_similarity(task1, task2)

        # Combined score (weighted average)
        combined = (
            0.5 * text_sim +
            0.3 * fuzzy_sim +
            0.2 * struct_sim
        )

        if combined >= threshold:
            results.append(SimilarityResult(
                task1=task1,
                task2=task2,
                text_similarity=text_sim,
                fuzzy_similarity=fuzzy_sim,
                structural_similarity=struct_sim,
                combined_score=combined
            ))

    # Sort by combined score (descending)
    results.sort(key=lambda x: x.combined_score, reverse=True)

    return results


def check_single_task_similarity(check_task: Task, existing_tasks: list[Task], threshold: float = 0.75) -> list[SimilarityResult]:
    """Compare a single task against all existing tasks."""
    if not existing_tasks:
        return []

    # Combine the check task with all existing tasks for TF-IDF calculation
    all_tasks = [check_task] + existing_tasks
    instructions = [task.instruction for task in all_tasks]

    # Calculate TF-IDF vectors
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words='english',
        ngram_range=(1, 2),
        max_features=1000
    )

    try:
        tfidf_matrix = vectorizer.fit_transform(instructions)
        similarity_matrix = cosine_similarity(tfidf_matrix)
    except ValueError as e:
        print(f"Warning: TF-IDF vectorization failed: {e}", file=sys.stderr)
        # Return empty results if vectorization fails
        return []

    results = []

    # Compare check_task (index 0) with all existing tasks (indices 1+)
    for i in range(1, len(all_tasks)):
        existing_task = existing_tasks[i - 1]

        # Get text similarity from the matrix
        text_sim = similarity_matrix[0, i]

        # Calculate other similarities
        fuzzy_sim = calculate_fuzzy_similarity(check_task.instruction, existing_task.instruction)
        struct_sim = calculate_structural_similarity(check_task, existing_task)

        # Combined score (weighted average)
        combined = (
            0.5 * text_sim +
            0.3 * fuzzy_sim +
            0.2 * struct_sim
        )

        if combined >= threshold:
            results.append(SimilarityResult(
                task1=check_task,
                task2=existing_task,
                text_similarity=text_sim,
                fuzzy_similarity=fuzzy_sim,
                structural_similarity=struct_sim,
                combined_score=combined
            ))

    # Sort by combined score (descending)
    results.sort(key=lambda x: x.combined_score, reverse=True)

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Detect similar tasks in tasks/ and our_tasks/ folders'
    )
    parser.add_argument(
        '--threshold',
        type=float,
        default=0.75,
        help='Similarity threshold (0-1, default: 0.75)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output file path (default: print to stdout)'
    )
    parser.add_argument(
        '--base-path',
        type=Path,
        default=Path.cwd(),
        help='Base path to search for tasks (default: current directory)'
    )
    parser.add_argument(
        '--check-task',
        type=Path,
        help='Path to a specific task directory to check against all existing tasks'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )

    args = parser.parse_args()

    # Determine mode: single task check vs all pairs
    if args.check_task:
        # Single task mode
        check_task_path = args.check_task / 'task.yaml'
        if not check_task_path.exists():
            print(f"Error: task.yaml not found at {check_task_path}", file=sys.stderr)
            sys.exit(1)

        print(f"Loading task from {args.check_task}...", file=sys.stderr)
        check_task = load_task(check_task_path, str(args.check_task))
        if not check_task:
            print(f"Error: Failed to load task from {check_task_path}", file=sys.stderr)
            sys.exit(1)

        print("Loading existing tasks...", file=sys.stderr)
        existing_tasks = load_all_tasks(args.base_path)
        print(f"Loaded {len(existing_tasks)} existing tasks", file=sys.stderr)

        print("Calculating similarities...", file=sys.stderr)
        results = check_single_task_similarity(check_task, existing_tasks, args.threshold)
        print(f"Found {len(results)} similar tasks", file=sys.stderr)
    else:
        # All pairs mode (original behavior)
        print("Loading tasks...", file=sys.stderr)
        tasks = load_all_tasks(args.base_path)
        print(f"Loaded {len(tasks)} tasks", file=sys.stderr)

        print("Calculating similarities...", file=sys.stderr)
        results = find_similar_tasks(tasks, args.threshold)
        print(f"Found {len(results)} similar task pairs", file=sys.stderr)

    # Output results
    output_file = open(args.output, 'w') if args.output else sys.stdout

    try:
        if args.json:
            json_results = [
                {
                    'task1': f"{r.task1.folder}/{r.task1.task_id}",
                    'task2': f"{r.task2.folder}/{r.task2.task_id}",
                    'text_similarity': r.text_similarity,
                    'fuzzy_similarity': r.fuzzy_similarity,
                    'structural_similarity': r.structural_similarity,
                    'combined_score': r.combined_score
                }
                for r in results
            ]
            json.dump(json_results, output_file, indent=2)
        else:
            output_file.write(f"Similar Tasks Report (threshold: {args.threshold})\n")
            output_file.write(f"Total pairs found: {len(results)}\n")

            for result in results:
                output_file.write(str(result))
                output_file.write("\n")
    finally:
        if args.output:
            output_file.close()
            print(f"Results written to {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
