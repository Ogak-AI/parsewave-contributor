#!/usr/bin/env python3
"""
Script to create a comparison table from terminal-bench results.json files.
Usage: python create_comparison_table.py <results1.json> <results2.json> ... --output <output.csv>
"""

import json
import csv
import argparse
import sys
from pathlib import Path
from collections import defaultdict


def parse_results_file(file_path, custom_name=None):
    """Parse a results.json file and extract task pass rates."""
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    # If custom name provided, use it
    if custom_name:
        model_name = custom_name
    else:
        # Get model name from file path (e.g., "claude4" from "claude4_20250920_184532")
        # If the parent dir doesn't have underscore, use the full parent name
        parent_name = Path(file_path).parent.name
        if '_' in parent_name:
            model_name = parent_name.split('_')[0]
        else:
            # For partial runs, might need a different naming scheme
            # Try to extract from metadata or use parent dir name
            model_name = parent_name
        
        # If there's metadata with model info, prefer that
        if 'metadata' in data and 'model' in data['metadata']:
            # Extract a clean model name from the full model path
            full_model = data['metadata']['model']
            if '/' in full_model:
                model_name = full_model.split('/')[-1].replace(':', '_')
            else:
                model_name = full_model.replace(':', '_')
    
    # Count successes per task
    task_stats = defaultdict(lambda: {'total': 0, 'passed': 0})
    
    for result in data['results']:
        task_id = result['task_id']
        is_resolved = result['is_resolved']
        
        task_stats[task_id]['total'] += 1
        if is_resolved:
            task_stats[task_id]['passed'] += 1
    
    # Calculate pass rates
    pass_rates = {}
    for task_id, stats in task_stats.items():
        pass_rate = stats['passed'] / stats['total'] if stats['total'] > 0 else 0
        pass_rates[task_id] = {
            'pass_rate': pass_rate,
            'passed': stats['passed'],
            'total': stats['total']
        }
    
    return model_name, pass_rates


def create_comparison_table(results_files, output_file):
    """Create a CSV comparison table from multiple results files.
    
    Args:
        results_files: List of tuples (file_path, custom_name) where custom_name can be None
        output_file: Path to output CSV file
    """
    all_models = {}
    all_tasks = set()
    
    # Parse all results files
    for file_path, custom_name in results_files:
        model_name, pass_rates = parse_results_file(file_path, custom_name)
        
        # Handle duplicate model names by appending a number
        original_model_name = model_name
        counter = 1
        while model_name in all_models:
            # Check if this is actually the same run (same tasks)
            existing_tasks = set(all_models[model_name].keys())
            new_tasks = set(pass_rates.keys())
            
            # If there's no overlap in tasks, treat as separate partial runs
            if not existing_tasks.intersection(new_tasks):
                # Combine the results for the same model
                for task_id, stats in pass_rates.items():
                    all_models[model_name][task_id] = stats
                break
            else:
                # Different run with same model, append counter
                counter += 1
                model_name = f"{original_model_name}_{counter}"
        else:
            all_models[model_name] = pass_rates
        
        all_tasks.update(pass_rates.keys())
    
    # Sort tasks for consistent output
    sorted_tasks = sorted(all_tasks)
    
    # Write CSV
    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        
        # Header row
        model_names = list(all_models.keys())
        header = ['Task'] + [f"{model}_rate" for model in model_names] + [f"{model}_trials" for model in model_names]
        writer.writerow(header)
        
        # Task rows
        for task in sorted_tasks:
            row = [task]
            for model in all_models.keys():
                if task in all_models[model]:
                    stats = all_models[model][task]
                    row.append(f"{stats['pass_rate']:.3f}")
                else:
                    row.append("")
            
            # Add trial counts for each model
            for model in all_models.keys():
                if task in all_models[model]:
                    stats = all_models[model][task]
                    row.append(f"{stats['passed']}/{stats['total']}")
                else:
                    row.append("")
            
            writer.writerow(row)
        
        # Overall row
        overall_row = ['Overall']
        for model_name, model_data in all_models.items():
            total_passed = sum(stats['passed'] for stats in model_data.values())
            total_trials = sum(stats['total'] for stats in model_data.values())
            overall_rate = total_passed / total_trials if total_trials > 0 else 0
            overall_row.append(f"{overall_rate:.3f}")
        
        # Add trial counts for overall
        for model_name, model_data in all_models.items():
            total_passed = sum(stats['passed'] for stats in model_data.values())
            total_trials = sum(stats['total'] for stats in model_data.values())
            overall_row.append(f"{total_passed}/{total_trials}")
        
        writer.writerow(overall_row)


def main():
    parser = argparse.ArgumentParser(description='Create comparison table from terminal-bench results')
    parser.add_argument('--output', '-o', default='cruft/comparison_table.csv', help='Output CSV file')
    
    args = parser.parse_args()
    
    processed_files = []
    results_files = [
        '/Users/plato/code/parsewave/runs/llama3.3_20251009_134719/results.json',
        '/Users/plato/code/parsewave/runs/llama3.3_20251009_154017/results.json',
        '/Users/plato/code/parsewave/runs/llama3.3_20251009_160741/results.json',
        '/Users/plato/code/parsewave/runs/claude4_20251009_163703/results.json',
        '/Users/plato/code/parsewave/runs/llama3.3_20251009_172623/results.json',
        '/Users/plato/code/parsewave/runs/gpt5_20251009_170132/results.json',
        '/Users/plato/code/parsewave/runs/llama3.3_20251009_173607/results.json',
    ]
    for file_spec in results_files:
        if ':' in file_spec and not Path(file_spec).exists():
            # Assume it's name:path format
            parts = file_spec.split(':', 1)
            if len(parts) == 2:
                custom_name, file_path = parts
                processed_files.append((file_path, custom_name))
            else:
                processed_files.append((file_spec, None))
        else:
            processed_files.append((file_spec, None))
    
    # Validate input files
    for file_path, _ in processed_files:
        if not Path(file_path).exists():
            print(f"Error: File {file_path} does not exist", file=sys.stderr)
            sys.exit(1)
    
    output_path = Path(args.output)
    output_dir = output_path.parent
    if output_dir.name == 'cruft' or 'cruft' in str(output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        create_comparison_table(processed_files, args.output)
        print(f"Comparison table saved to {args.output}")
    except Exception as e:
        print(f"Error creating comparison table: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()