#!/usr/bin/env python3
"""
Local Full Check Script

This script mimics the bot's full-check command by running ParseWave commands locally.
It implements the same workflow:
0. Phase 0: AI Detection check on task.yaml and solution.sh
1. Phase 1: Run Oracle and NOP checks in parallel (fail-fast)
2. Phase 2: Run tb_check and two tb_run commands in parallel (only if Phase 1 succeeds)
3. Phase 3: Run tb_debug conditionally for each tb_run (only if accuracy < 100%)

Usage:
    python full_check.py --task-id hello-world [options]

Examples:
    # Basic usage (uses defaults: terminus-2 agent with gpt-oss-120b and gpt-5)
    python full_check.py --task-id hello-world

    # Override default agents and models
    python full_check.py --task-id hello-world \
        --tb-run-small-agent claude-code \
        --tb-run-small-model claude-sonnet-3-5 \
        --tb-run-large-agent claude-code \
        --tb-run-large-model claude-sonnet-4-5

    # Custom paths
    python full_check.py --task-id my-task --tasks-dir custom_tasks

Requirements:
    - Terminal-Bench must be installed (tb command available)
    - Python 3.7+
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Import AI detection module
try:
    from check_ai_gptzero import GPTZeroChecker, analyze_task
except ImportError:
    # If not importable as module, try relative import
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_ai_gptzero",
                                                   os.path.join(os.path.dirname(__file__), "check_ai_gptzero.py"))
    check_ai_gptzero = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_ai_gptzero)
    GPTZeroChecker = check_ai_gptzero.GPTZeroChecker
    analyze_task = check_ai_gptzero.analyze_task


@dataclass
class CommandResult:
    """Result of a command execution"""
    success: bool
    stdout: str
    stderr: str
    return_code: int
    duration: float
    json_output: Optional[Dict] = None
    accuracy: Optional[float] = None
    result_type: Optional[str] = None  # tb_positive, tb_negative, tb_system_error, job_system_error
    n_commands_list: Optional[List[int]] = None  # List of n_commands from each trial
    min_commands: Optional[int] = None  # Minimum n_commands from successful trials
    commands_threshold_met: Optional[bool] = None  # Whether all successful attempts meet minimum command threshold
    successful_n_commands: Optional[List[int]] = None  # List of n_commands from successful trials only


@dataclass
class FullCheckConfig:
    """Configuration for full check execution"""
    task_id: Optional[str]
    tasks_dir: str
    output_dir: str
    skip_steps: List[str]

    # TB Run Small (typically OSS model)
    tb_run_small_agent: str
    tb_run_small_model: Optional[str]
    tb_run_small_n_attempts: int
    tb_run_small_n_concurrent: int
    tb_run_small_use_subscription: bool

    # TB Run Large (typically GPT-5 or other frontier model)
    tb_run_large_agent: str
    tb_run_large_model: Optional[str]
    tb_run_large_n_attempts: int
    tb_run_large_n_concurrent: int
    tb_run_large_use_subscription: bool

    # TB Check
    tb_check_agent: Optional[str]
    tb_check_model: Optional[str]

    # TB Debug
    tb_debug_agent: Optional[str]
    tb_debug_model: Optional[str]

    # Minimum commands thresholds (for successful attempts)
    min_commands_threshold_small: int = 10  # Small model must use >= 10 commands (proves non-trivial task)
    min_commands_threshold_large: int = 0   # Large model has no minimum (can solve efficiently)


class FullCheckRunner:
    """Orchestrates the full check workflow"""

    def __init__(self, config: FullCheckConfig):
        self.config = config
        self.results: Dict[str, CommandResult] = {}
        self.cancelled_jobs: List[str] = []

    def extract_n_commands_info(self, json_output: Optional[Dict], command_type: str, min_threshold: int = 10) -> Tuple[Optional[List[int]], Optional[int], Optional[bool], Optional[List[int]]]:
        """
        Extract n_commands information from TB run results.
        Returns: (n_commands_list, min_commands_from_successful_trials, commands_threshold_met, successful_n_commands_list)

        Only applicable for TB_RUN, TB_ORACLE, TB_NOP commands.

        commands_threshold_met:
        - True if ALL successful attempts have n_commands >= min_threshold
        - False if ANY successful attempt has n_commands < min_threshold
        - None if no successful attempts or n_commands data unavailable

        successful_n_commands_list:
        - List of n_commands from only the successful (is_resolved=true) attempts
        """
        if command_type not in ['TB_RUN', 'TB_ORACLE', 'TB_NOP'] or not json_output:
            return None, None, None, None

        n_commands_list = []
        successful_n_commands = []

        results = json_output.get('results', [])
        for result in results:
            n_commands = result.get('n_commands')
            if n_commands is not None:
                n_commands_list.append(n_commands)
                # Only track successful trials (is_resolved=true)
                if result.get('is_resolved', False):
                    successful_n_commands.append(n_commands)

        # Calculate minimum from successful trials only
        min_commands = min(successful_n_commands) if successful_n_commands else None

        # Check if all successful attempts meet the minimum threshold
        # Only check for TB_RUN (not TB_ORACLE or TB_NOP)
        commands_threshold_met = None
        if command_type == 'TB_RUN' and successful_n_commands:
            commands_threshold_met = all(n >= min_threshold for n in successful_n_commands)

        return (
            n_commands_list if n_commands_list else None,
            min_commands,
            commands_threshold_met,
            successful_n_commands if successful_n_commands else None
        )

    def parse_results_json(self, output_path: str, command_type: str, run_id: Optional[str] = None) -> Tuple[Optional[Dict], Optional[float]]:
        """
        Parse results.json file based on command type.
        Returns: (json_output, accuracy)

        For TB_RUN/TB_ORACLE/TB_NOP: output_path is a directory, looks for <output_path>/<run_id>/results.json
        For TB_CHECK/TB_DEBUG: output_path is the JSON file itself
        """
        json_output = None
        accuracy = None

        try:
            # Determine the actual JSON file path based on command type
            if command_type in ['TB_RUN', 'TB_ORACLE', 'TB_NOP']:
                # For run commands, output_path is a directory
                # If run_id is provided, look specifically in output_path/run_id/
                if run_id and os.path.isdir(output_path):
                    # Look for results.json in the run_id subdirectory
                    run_id_dir = os.path.join(output_path, run_id)
                    if os.path.isdir(run_id_dir):
                        json_path = os.path.join(run_id_dir, 'results.json')
                        if not os.path.exists(json_path):
                            return None, None
                    else:
                        return None, None
                elif os.path.isdir(output_path):
                    # Fallback: Find all results.json files and use the most recent
                    results_files = []
                    for root, dirs, files in os.walk(output_path):
                        if 'results.json' in files:
                            results_files.append(os.path.join(root, 'results.json'))

                    if results_files:
                        # Use the most recently modified one
                        json_path = max(results_files, key=os.path.getmtime)
                    else:
                        return None, None
                else:
                    return None, None
            else:
                # For check/debug commands, output_path points to the JSON file
                json_path = output_path

            # Read and parse the JSON file
            if os.path.exists(json_path):
                with open(json_path, 'r') as f:
                    json_output = json.load(f)

                # Extract accuracy (for run commands)
                # Note: Use 'if...is not None' instead of 'or' because accuracy can be 0.0
                if command_type in ['TB_RUN', 'TB_ORACLE', 'TB_NOP']:
                    accuracy = json_output.get('accuracy')
                    if accuracy is None:
                        accuracy = json_output.get('overall_accuracy')

            return json_output, accuracy

        except Exception as e:
            print(f"Warning: Failed to parse results JSON at {output_path}: {e}")
            return None, None

    def determine_result_type(self, json_output: Dict, command_type: str, accuracy: Optional[float], stderr: str, stdout: str, commands_threshold_met: Optional[bool] = None) -> str:
        """
        Determine result type based on command type and result content.
        Returns: 'tb_positive', 'tb_negative', or 'tb_system_error'

        Based on runner-manager.js:636-819 determineTBResultType()

        Also checks if commands_threshold_met is False (for TB_RUN only) and returns tb_negative if so.
        """

        # Check for minimum commands threshold violation first (for TB_RUN only)
        if command_type == 'TB_RUN' and commands_threshold_met is False:
            print(f"  ⚠️  Commands threshold not met: one or more successful attempts have < 10 terminal commands")
            return 'tb_negative'

        # Check NOP and ORACLE first (before system error checks) since they have special logic
        # NOP is special - tests SHOULD fail (baseline validation)
        # SUCCESS: accuracy == 0.0 (tb_positive)
        # FAILURE: accuracy > 0.0 (tb_negative)
        if command_type == 'TB_NOP':
            if accuracy is not None and accuracy > 0.0:
                return 'tb_negative'
            # If accuracy is 0.0 or None, consider it positive (NOP should fail)
            return 'tb_positive'

        # Oracle must have 100% accuracy
        # FAILURE: accuracy < 1.0 (tb_negative)
        if command_type == 'TB_ORACLE':
            if accuracy is not None and accuracy < 1.0:
                return 'tb_negative'
            # If accuracy is 1.0, check for system errors below

        # Check for TB system errors (runner-manager.js:639-693)
        tb_error_patterns = [
            'subscription', 'authentication', 'api key', 'rate limit',
            'configuration error', 'invalid.*agent', 'agent.*not found',
            'missing.*required'
        ]

        # Pattern matching in stderr/stdout
        import re
        has_system_error = any(
            re.search(pattern, stderr, re.IGNORECASE) or re.search(pattern, stdout, re.IGNORECASE)
            for pattern in tb_error_patterns
        )

        if has_system_error:
            return 'tb_system_error'

        # If we expected JSON output but didn't get it, that's a system error
        expects_json = command_type in ['TB_CHECK', 'TB_DEBUG', 'TB_RUN', 'TB_ORACLE', 'TB_NOP']
        if expects_json and not json_output:
            return 'tb_system_error'

        # Check for system errors in failure_mode field (runner-manager.js:665-693)
        # Only for TB_RUN and TB_ORACLE (not NOP, which is handled above)
        if command_type in ['TB_RUN', 'TB_ORACLE'] and json_output:
            if 'results' in json_output and isinstance(json_output['results'], list):
                system_error_modes = [
                    'unknown_agent_error',      # Agent infrastructure error
                    'agent_timeout',            # Agent exceeded time limit
                    'context_length_exceeded',  # Model context limit hit
                    'output_length_exceeded',   # Model output limit hit
                    'agent_installation_failed' # Agent setup failed
                ]

                # Check if any result has a system error failure mode
                for result in json_output['results']:
                    if result.get('failure_mode') in system_error_modes:
                        print(f"  ⚠️  System error detected: {result.get('failure_mode')}")
                        return 'tb_system_error'

        # Now check for tb_negative vs tb_positive based on command type
        # (runner-manager.js:695-815)
        # Note: NOP and ORACLE already handled above

        if command_type == 'TB_RUN':
            # Regular run: check if any attempts failed
            # FAILURE: accuracy < 1.0 (tb_negative)
            # (runner-manager.js:766-771)
            if accuracy is not None and accuracy < 1.0:
                return 'tb_negative'

        elif command_type == 'TB_CHECK':
            # Check if any checks have outcome='fail'
            # (runner-manager.js:789-796)
            if json_output:
                has_issues = any(
                    check.get('outcome') == 'fail'
                    for check in json_output.values()
                    if isinstance(check, dict)
                )
                if has_issues:
                    return 'tb_negative'

        elif command_type == 'TB_DEBUG':
            # Check outcome field
            # FAILURE: outcome == 'FAIL' (tb_negative)
            # (runner-manager.js:809-814)
            if json_output:
                outcome = json_output.get('outcome')
                if outcome == 'FAIL':
                    return 'tb_negative'

        # If we get here, it's a positive result
        # (runner-manager.js:817-818)
        return 'tb_positive'

    async def run_command(self, name: str, command: List[str], output_path: str, command_type: str, timeout: Optional[int] = None, min_commands_threshold: int = 10) -> CommandResult:
        """Run a shell command and capture output"""
        print(f"\n{'='*80}")
        print(f"[{name}] Starting...")
        print(f"Command: {' '.join(command)}")
        print(f"{'='*80}\n")

        start_time = time.time()

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd()
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                duration = time.time() - start_time
                print(f"[{name}] ❌ TIMEOUT after {duration:.1f}s")
                return CommandResult(
                    success=False,
                    stdout="",
                    stderr=f"Command timed out after {timeout}s",
                    return_code=-1,
                    duration=duration
                )

            duration = time.time() - start_time
            stdout_str = stdout.decode('utf-8', errors='replace')
            stderr_str = stderr.decode('utf-8', errors='replace')

            # Print output (abbreviated)
            if stdout_str:
                # Only show last 50 lines to avoid clutter
                lines = stdout_str.split('\n')
                if len(lines) > 50:
                    print(f"[{name}] STDOUT (last 50 lines):\n" + '\n'.join(lines[-50:]))
                else:
                    print(f"[{name}] STDOUT:\n{stdout_str}")

            # Extract run-id from command if present (for finding the correct results.json)
            run_id = None
            try:
                run_id_index = command.index('--run-id')
                if run_id_index + 1 < len(command):
                    run_id = command[run_id_index + 1]
            except (ValueError, IndexError):
                pass

            # Parse results.json file to get actual json output and accuracy
            json_output, accuracy = self.parse_results_json(output_path, command_type, run_id)

            # Extract n_commands information
            n_commands_list, min_commands, commands_threshold_met, successful_n_commands = self.extract_n_commands_info(
                json_output, command_type, min_commands_threshold
            )

            # Determine result type based on bot's logic
            if json_output is None and process.returncode != 0:
                result_type = 'job_system_error'
                success = False
            else:
                result_type = self.determine_result_type(
                    json_output, command_type, accuracy, stderr_str, stdout_str, commands_threshold_met
                )
                success = (result_type == 'tb_positive')

            # Display result
            status_icon = "✅" if success else "❌"
            print(f"\n[{name}] {status_icon} Completed in {duration:.1f}s (exit code: {process.returncode})")
            if accuracy is not None:
                accuracy_pct = accuracy * 100 if isinstance(accuracy, float) else (100 if accuracy else 0)
                print(f"[{name}] Accuracy: {accuracy_pct:.1f}%")
            if min_commands is not None:
                if min_commands_threshold > 0:
                    threshold_icon = "✅" if commands_threshold_met else "❌"
                    print(f"[{name}] Min Commands: {min_commands} (threshold >= {min_commands_threshold}: {threshold_icon})")
                else:
                    print(f"[{name}] Min Commands: {min_commands} (no threshold)")
            print(f"[{name}] Result Type: {result_type}")
            print(f"[{name}] Success: {success}")

            return CommandResult(
                success=success,
                stdout=stdout_str,
                stderr=stderr_str,
                return_code=process.returncode,
                duration=duration,
                json_output=json_output,
                accuracy=accuracy,
                result_type=result_type,
                n_commands_list=n_commands_list,
                min_commands=min_commands,
                commands_threshold_met=commands_threshold_met,
                successful_n_commands=successful_n_commands
            )

        except Exception as e:
            duration = time.time() - start_time
            print(f"[{name}] ❌ ERROR: {e}")
            return CommandResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1,
                duration=duration
            )

    async def run_parallel_with_failfast(
        self,
        commands: Dict[str, Tuple[List[str], str, str, int]],  # name -> (command, output_path, command_type, min_threshold)
        timeout: Optional[int] = None
    ) -> Dict[str, CommandResult]:
        """Run commands in parallel, cancel all if any fails (fail-fast)"""
        tasks = {}
        results = {}

        # Create all tasks
        for name, (command, output_path, command_type, min_threshold) in commands.items():
            tasks[name] = asyncio.create_task(self.run_command(name, command, output_path, command_type, timeout, min_threshold))

        # Wait for first completion or failure
        pending = set(tasks.values())

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

            for task in done:
                # Find which command completed
                task_name = None
                for name, t in tasks.items():
                    if t == task:
                        task_name = name
                        break

                if task_name:
                    result = await task
                    results[task_name] = result

                    # If failed, cancel all other tasks
                    if not result.success:
                        print(f"\n{'='*80}")
                        print(f"❌ FAIL-FAST: {task_name} failed, cancelling sibling jobs...")
                        print(f"{'='*80}\n")

                        for other_name, other_task in tasks.items():
                            if other_name != task_name:
                                if not other_task.done():
                                    print(f"[{other_name}] 🚫 Cancelled due to {task_name} failure")
                                    other_task.cancel()
                                    self.cancelled_jobs.append(other_name)
                                    try:
                                        await other_task
                                    except asyncio.CancelledError:
                                        pass
                                    results[other_name] = CommandResult(
                                        success=False,
                                        stdout="",
                                        stderr=f"Cancelled because sibling job {task_name} failed",
                                        return_code=-1,
                                        duration=0.0
                                    )
                                else:
                                    # Task already completed (both failed at same time)
                                    if other_name not in results:
                                        try:
                                            results[other_name] = await other_task
                                        except Exception:
                                            results[other_name] = CommandResult(
                                                success=False,
                                                stdout="",
                                                stderr="Task failed",
                                                return_code=-1,
                                                duration=0.0
                                            )

                        return results

        return results

    async def run_parallel(
        self,
        commands: Dict[str, Tuple[List[str], str, str, int]],  # name -> (command, output_path, command_type, min_threshold)
        timeout: Optional[int] = None
    ) -> Dict[str, CommandResult]:
        """Run commands in parallel without fail-fast"""
        tasks = {
            name: asyncio.create_task(self.run_command(name, cmd, output_path, cmd_type, timeout, min_threshold))
            for name, (cmd, output_path, cmd_type, min_threshold) in commands.items()
        }

        results = {}
        for name, task in tasks.items():
            results[name] = await task

        return results

    def should_run_tb_debug(self, tb_run_result: CommandResult) -> bool:
        """
        Determine if tb_debug should run based on tb_run result.

        TB Debug should ONLY run when there are failed attempts (accuracy < 100%).
        It should NOT run when the only issue is commands threshold not being met,
        as there would be no failed attempts to analyze.
        """
        # Only check accuracy, not the overall success flag
        # (success can be False due to commands threshold, but that shouldn't trigger TB Debug)
        if tb_run_result.accuracy is not None:
            if isinstance(tb_run_result.accuracy, bool):
                return not tb_run_result.accuracy
            elif isinstance(tb_run_result.accuracy, (int, float)):
                return tb_run_result.accuracy < 1.0

        # If accuracy is None, check if result_type indicates actual failures
        # (not just commands threshold issues)
        if tb_run_result.result_type in ['tb_system_error', 'job_system_error']:
            return True

        # Default: don't run debug if we can't determine there are failed attempts
        return False

    def build_tb_command(
        self,
        base_command: str,
        task_id: Optional[str] = None,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        n_attempts: Optional[int] = None,
        n_concurrent: Optional[int] = None,
        use_subscription: bool = False,
        output_path: Optional[str] = None,
        run_id: Optional[str] = None,
        run_dir: Optional[str] = None,
        tasks_dir: Optional[str] = None
    ) -> List[str]:
        """Build a terminal-bench command with parameters"""
        cmd = ['uv', 'run', 'tb'] + base_command.split()

        # Add agent
        if agent:
            cmd.extend(['--agent', agent])

        # Add model
        if model:
            cmd.extend(['--model', model])

        # Add task-id (for run commands)
        if task_id and 'run' in base_command:
            cmd.extend(['--task-id', task_id])

        # Add positional task-id (for tasks check/debug commands)
        if task_id and ('check' in base_command or 'debug' in base_command):
            cmd.append(task_id)

        # Add n-attempts
        if n_attempts is not None:
            cmd.extend(['--n-attempts', str(n_attempts)])

        # Add n-concurrent
        if n_concurrent is not None:
            cmd.extend(['--n-concurrent', str(n_concurrent)])

        # Add use-subscription
        if use_subscription:
            cmd.append('--use-subscription')

        # Add dataset-path (for run commands)
        if tasks_dir and 'run' in base_command:
            cmd.extend(['--dataset-path', tasks_dir])

        # Add tasks-dir (for check/debug commands)
        if tasks_dir and ('check' in base_command or 'debug' in base_command):
            cmd.extend(['--tasks-dir', tasks_dir])

        # Add output-path
        if output_path:
            cmd.extend(['--output-path', output_path])

        # Add run-id
        # For 'run' commands: ensures unique Docker project names to avoid conflicts when running multiple agents in parallel
        # For 'debug' commands: specifies which run to analyze
        if run_id:
            if ('run' in base_command and 'debug' not in base_command) or 'debug' in base_command:
                cmd.extend(['--run-id', run_id])

        # Add runs-dir (for debug commands)
        # TB debug needs the parent directory containing all runs
        if run_dir and 'debug' in base_command:
            cmd.extend(['--runs-dir', run_dir])

        return cmd

    async def run_full_check(self) -> bool:
        """Run the complete full check workflow"""

        # Create timestamped run directory: full-check-{date_time}
        import datetime
        import subprocess
        run_timestamp = datetime.datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
        self.run_dir = os.path.join(self.config.output_dir, f"full-check-{run_timestamp}")
        os.makedirs(self.run_dir, exist_ok=True)

        # Clean up unused Docker networks to prevent IPv4 address pool exhaustion
        print("Cleaning up unused Docker networks...")
        try:
            subprocess.run(['docker', 'network', 'prune', '-f'], check=False, capture_output=True)
        except Exception as e:
            print(f"Warning: Failed to clean up Docker networks: {e}")

        print(f"""
{'='*80}
FULL CHECK WORKFLOW STARTING
{'='*80}
Configuration:
  Task ID: {self.config.task_id}
  Tasks Dir: {self.config.tasks_dir}
  Run Directory: {self.run_dir}

  TB Run Small:
    Agent: {self.config.tb_run_small_agent}
    Model: {self.config.tb_run_small_model or '(default)'}
    Attempts: {self.config.tb_run_small_n_attempts}
    Concurrent: {self.config.tb_run_small_n_concurrent}

  TB Run Large:
    Agent: {self.config.tb_run_large_agent}
    Model: {self.config.tb_run_large_model or '(default)'}
    Attempts: {self.config.tb_run_large_n_attempts}
    Concurrent: {self.config.tb_run_large_n_concurrent}
{'='*80}
""")

        # ===================================================================
        # PHASE 0: AI Detection check
        # ===================================================================
        print(f"\n{'='*80}")
        print("PHASE 0: AI Detection Check")
        print(f"{'='*80}")

        ai_detection_result = None
        ai_detection_success = False
        ai_detection_result_type = "tb_system_error"
        ai_detection_duration = 0.0

        gptzero_api_key = os.environ.get("GPTZERO_API_KEY")

        if not gptzero_api_key:
            print("⚠️  GPTZERO_API_KEY not found in environment variables")
            print("   Skipping AI detection phase")
            ai_detection_result_type = "tb_system_error"
        else:
            try:
                print(f"Checking task files for AI-generated content...")
                start_time = time.time()
                checker = GPTZeroChecker(gptzero_api_key)
                ai_detection_result_full = analyze_task(self.config.task_id, self.config.tasks_dir, checker)
                ai_detection_duration = time.time() - start_time

                # Create short output version (top-level fields only, no nested objects)
                ai_detection_result = {
                    "task_id": ai_detection_result_full.get("task_id"),
                    "task_path": ai_detection_result_full.get("task_path"),
                    "files_analyzed": ai_detection_result_full.get("files_analyzed"),
                    "documents": []
                }

                # Extract only top-level fields from each document
                for doc in ai_detection_result_full.get("documents", []):
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
                    ai_detection_result["documents"].append(short_doc)

                # Save AI detection results (short version)
                ai_output_file = os.path.join(self.run_dir, 'ai-detect.json')
                with open(ai_output_file, 'w') as f:
                    json.dump(ai_detection_result, f, indent=2)

                # Determine result type based on criterion: completely_generated_prob < 0.7 for both files
                # tb_positive = passes criterion (both files < 0.7, likely human-written)
                # tb_negative = fails criterion (any file >= 0.7, likely AI-generated)
                # tb_system_error = error occurred

                if "error" in ai_detection_result_full:
                    print(f"❌ AI Detection failed: {ai_detection_result_full['error']}")
                    ai_detection_success = False
                    ai_detection_result_type = "tb_system_error"
                    # Include error in short result
                    ai_detection_result["error"] = ai_detection_result_full["error"]
                else:
                    documents = ai_detection_result.get("documents", [])

                    if not documents:
                        print(f"❌ AI Detection failed: No documents returned")
                        ai_detection_success = False
                        ai_detection_result_type = "tb_system_error"
                    else:
                        # Check if ALL files pass the criterion (completely_generated_prob < 0.7)
                        all_pass = True
                        for doc in documents:
                            completely_generated_prob = doc.get("completely_generated_prob", 1.0)
                            if completely_generated_prob >= 0.7:
                                all_pass = False
                                break

                        if all_pass:
                            ai_detection_success = True
                            ai_detection_result_type = "tb_positive"
                            print(f"✅ AI Detection completed - PASS (all files < 70% AI probability)")
                        else:
                            ai_detection_success = True  # Completed successfully, but failed criterion
                            ai_detection_result_type = "tb_negative"
                            print(f"❌ AI Detection completed - FAIL (one or more files >= 70% AI probability)")

                        # Display details for each file
                        for doc in documents:
                            predicted_class = doc.get("predicted_class", "unknown")
                            confidence = doc.get("confidence_score", 0)
                            completely_generated_prob = doc.get("completely_generated_prob", 0)
                            emoji = "👤" if predicted_class == "human" else "🤖"
                            status = "✅" if completely_generated_prob < 0.7 else "❌"
                            print(f"   {status} {emoji} {predicted_class.upper()} ({confidence:.1%} confidence, {completely_generated_prob:.1%} completely AI)")

                print(f"📄 AI detection results saved to: {ai_output_file}")

            except Exception as e:
                print(f"❌ AI Detection failed with error: {e}")
                ai_detection_result = {"error": str(e)}
                ai_detection_success = False
                ai_detection_result_type = "tb_system_error"
                ai_detection_duration = 0.0

        # Store AI detection results in the same format as other phases
        self.results['ai_detect'] = CommandResult(
            success=ai_detection_success,
            stdout="",
            stderr=str(ai_detection_result.get("error", "")) if ai_detection_result and "error" in ai_detection_result else "",
            return_code=0 if ai_detection_success else 1,
            duration=ai_detection_duration,
            json_output=ai_detection_result,
            accuracy=None,
            result_type=ai_detection_result_type
        )

        print()

        # ===================================================================
        # PHASE 1: Oracle and NOP checks in parallel
        # ===================================================================
        print(f"\n{'='*80}")
        print("PHASE 1: Running Oracle and NOP checks in parallel")
        print(f"{'='*80}")

        # Use run IDs: tb-oracle, tb-nop
        # TB will create subdirectories: run_dir/{run_id}/results.json
        # We pass run_dir as output_path, and TB creates the run_id subdirectory
        oracle_output_path = self.run_dir
        nop_output_path = self.run_dir

        phase1_commands = {
            'oracle': (
                self.build_tb_command(
                    'run',
                    task_id=self.config.task_id,
                    agent='oracle',
                    tasks_dir=self.config.tasks_dir,
                    output_path=oracle_output_path,
                    run_id='tb-oracle'
                ),
                oracle_output_path,
                'TB_ORACLE',
                0  # No threshold for oracle
            ),
            'nop': (
                self.build_tb_command(
                    'run',
                    task_id=self.config.task_id,
                    agent='nop',
                    tasks_dir=self.config.tasks_dir,
                    output_path=nop_output_path,
                    run_id='tb-nop'
                ),
                nop_output_path,
                'TB_NOP',
                0  # No threshold for nop
            )
        }

        # Run both Oracle and NOP without fail-fast (let both complete)
        phase1_results = await self.run_parallel(phase1_commands, timeout=600)
        self.results.update(phase1_results)

        # Check if Phase 1 succeeded - both must be tb_positive
        oracle_result = phase1_results.get('oracle')
        nop_result = phase1_results.get('nop')

        oracle_tb_positive = oracle_result and oracle_result.result_type == 'tb_positive'
        nop_tb_positive = nop_result and nop_result.result_type == 'tb_positive'

        if not (oracle_tb_positive and nop_tb_positive):
            print(f"\n{'='*80}")
            print("❌ PHASE 1 FAILED - Not both tb_positive, stopping workflow")
            print(f"  Oracle: {oracle_result.result_type if oracle_result else 'N/A'}")
            print(f"  NOP: {nop_result.result_type if nop_result else 'N/A'}")
            print(f"{'='*80}\n")

            # Still print summary and write results even on failure
            self.print_summary()
            self.write_combined_results()

            return False

        print(f"\n{'='*80}")
        print("✅ PHASE 1 PASSED - Both Oracle and NOP are tb_positive")
        print(f"{'='*80}")

        # ===================================================================
        # PHASE 2: TB Check and two TB Runs in parallel
        # ===================================================================
        if 'phase2' in self.config.skip_steps:
            print(f"\n{'='*80}")
            print("⏭️  PHASE 2 SKIPPED (--skip-steps phase2)")
            print(f"{'='*80}")
        else:
            print(f"\n{'='*80}")
            print("PHASE 2: Running TB Check and TB Runs in parallel")
            print(f"{'='*80}")

            phase2_commands = {}

            # TB Check
            if 'tb_check' not in self.config.skip_steps:
                # TB check outputs directly to a JSON file, not a directory
                check_output_path = os.path.join(self.run_dir, 'tb-check.json')
                phase2_commands['tb_check'] = (
                    self.build_tb_command(
                        'tasks check',
                        task_id=self.config.task_id,
                        agent=self.config.tb_check_agent,
                        model=self.config.tb_check_model,
                        tasks_dir=self.config.tasks_dir,
                        output_path=check_output_path
                    ),
                    check_output_path,
                    'TB_CHECK',
                    0  # No threshold for check
                )
            else:
                print("  ⏭️  Skipping TB Check (--skip-steps tb_check)")

            # TB Run Small
            if 'tb_run_small' not in self.config.skip_steps:
                run_small_output_path = self.run_dir
                phase2_commands['tb_run_small'] = (
                    self.build_tb_command(
                        'run',
                        task_id=self.config.task_id,
                        agent=self.config.tb_run_small_agent,
                        model=self.config.tb_run_small_model,
                        n_attempts=self.config.tb_run_small_n_attempts,
                        n_concurrent=self.config.tb_run_small_n_concurrent,
                        use_subscription=self.config.tb_run_small_use_subscription,
                        tasks_dir=self.config.tasks_dir,
                        output_path=run_small_output_path,
                        run_id='tb-run-small'
                    ),
                    run_small_output_path,
                    'TB_RUN',
                    self.config.min_commands_threshold_small  # Small model threshold (default: 10)
                )
            else:
                print("  ⏭️  Skipping TB Run Small (--skip-steps tb_run_small)")

            # TB Run Large
            if 'tb_run_large' not in self.config.skip_steps:
                run_large_output_path = self.run_dir
                phase2_commands['tb_run_large'] = (
                    self.build_tb_command(
                        'run',
                        task_id=self.config.task_id,
                        agent=self.config.tb_run_large_agent,
                        model=self.config.tb_run_large_model,
                        n_attempts=self.config.tb_run_large_n_attempts,
                        n_concurrent=self.config.tb_run_large_n_concurrent,
                        use_subscription=self.config.tb_run_large_use_subscription,
                        tasks_dir=self.config.tasks_dir,
                        output_path=run_large_output_path,
                        run_id='tb-run-large'
                    ),
                    run_large_output_path,
                    'TB_RUN',
                    self.config.min_commands_threshold_large  # Large model threshold (default: 0)
                )
            else:
                print("  ⏭️  Skipping TB Run Large (--skip-steps tb_run_large)")

            if phase2_commands:
                phase2_results = await self.run_parallel(phase2_commands, timeout=3600)
                self.results.update(phase2_results)

                # Count Phase 2 successes (tolerateFailure = true, so we continue even if some fail)
                phase2_success_count = sum(1 for r in phase2_results.values() if r.success)
                print(f"\n{'='*80}")
                print(f"PHASE 2 COMPLETE: {phase2_success_count}/{len(phase2_commands)} succeeded")
                print(f"{'='*80}")
            else:
                print(f"\n{'='*80}")
                print("PHASE 2: No commands to run (all skipped)")
                print(f"{'='*80}")

        # ===================================================================
        # PHASE 3: TB Debug (conditional based on accuracy)
        # ===================================================================
        if 'phase3' in self.config.skip_steps:
            print(f"\n{'='*80}")
            print("⏭️  PHASE 3 SKIPPED (--skip-steps phase3)")
            print(f"{'='*80}")
        else:
            print(f"\n{'='*80}")
            print("PHASE 3: Running TB Debug conditionally (only if accuracy < 100%)")
            print(f"{'='*80}")

            phase3_commands = {}

            # TB Debug Small (if needed)
            if 'tb_debug_small' in self.config.skip_steps:
                print(f"\n[tb_debug_small] ⏭️  Skipping (--skip-steps tb_debug_small)")
            elif 'tb_run_small' in self.config.skip_steps or 'phase2' in self.config.skip_steps:
                print(f"\n[tb_debug_small] ⏭️  Skipping (TB Run Small was skipped)")
            elif 'tb_run_small' in self.results:
                tb_run_small_result = self.results['tb_run_small']
                should_debug_small = self.should_run_tb_debug(tb_run_small_result)

                if should_debug_small:
                    print(f"\n[tb_debug_small] Will run (accuracy < 100% or failed)")
                    run_id_small = 'tb-run-small'
                    # TB debug outputs directly to a JSON file
                    debug_small_output_path = os.path.join(self.run_dir, 'tb-debug-small.json')
                    # TB debug needs --runs-dir (parent directory) and --run-id
                    phase3_commands['tb_debug_small'] = (
                        self.build_tb_command(
                            'tasks debug',
                            task_id=self.config.task_id,
                            agent=self.config.tb_debug_agent,
                            model=self.config.tb_debug_model,
                            tasks_dir=self.config.tasks_dir,
                            run_id=run_id_small,
                            run_dir=self.run_dir,
                            output_path=debug_small_output_path
                        ),
                        debug_small_output_path,
                        'TB_DEBUG',
                        0  # No threshold for debug
                    )
                else:
                    print(f"\n[tb_debug_small] ⏭️  Skipping (accuracy = 100%)")
                    self.results['tb_debug_small'] = CommandResult(
                        success=True,
                        stdout="",
                        stderr="Skipped - accuracy = 100%",
                        return_code=0,
                        duration=0.0,
                        result_type='tb_positive'  # Skipped is not an error
                    )

            # TB Debug Large (if needed)
            if 'tb_debug_large' in self.config.skip_steps:
                print(f"\n[tb_debug_large] ⏭️  Skipping (--skip-steps tb_debug_large)")
            elif 'tb_run_large' in self.config.skip_steps or 'phase2' in self.config.skip_steps:
                print(f"\n[tb_debug_large] ⏭️  Skipping (TB Run Large was skipped)")
            elif 'tb_run_large' in self.results:
                tb_run_large_result = self.results['tb_run_large']
                should_debug_large = self.should_run_tb_debug(tb_run_large_result)

                if should_debug_large:
                    print(f"\n[tb_debug_large] Will run (accuracy < 100% or failed)")
                    run_id_large = 'tb-run-large'
                    # TB debug outputs directly to a JSON file
                    debug_large_output_path = os.path.join(self.run_dir, 'tb-debug-large.json')
                    # TB debug needs --runs-dir (parent directory) and --run-id
                    phase3_commands['tb_debug_large'] = (
                        self.build_tb_command(
                            'tasks debug',
                            task_id=self.config.task_id,
                            agent=self.config.tb_debug_agent,
                            model=self.config.tb_debug_model,
                            tasks_dir=self.config.tasks_dir,
                            run_id=run_id_large,
                            run_dir=self.run_dir,
                            output_path=debug_large_output_path
                        ),
                        debug_large_output_path,
                        'TB_DEBUG',
                        0  # No threshold for debug
                    )
                else:
                    print(f"\n[tb_debug_large] ⏭️  Skipping (accuracy = 100%)")
                    self.results['tb_debug_large'] = CommandResult(
                        success=True,
                        stdout="",
                        stderr="Skipped - accuracy = 100%",
                        return_code=0,
                        duration=0.0,
                        result_type='tb_positive'  # Skipped is not an error
                    )

            if phase3_commands:
                phase3_results = await self.run_parallel(phase3_commands, timeout=1800)
                self.results.update(phase3_results)

                phase3_success_count = sum(1 for r in phase3_results.values() if r.success)
                print(f"\n{'='*80}")
                print(f"PHASE 3 COMPLETE: {phase3_success_count}/{len(phase3_commands)} succeeded")
                print(f"{'='*80}")
            else:
                print(f"\n{'='*80}")
                print("PHASE 3: No debug commands needed (all runs at 100% accuracy or skipped)")
                print(f"{'='*80}")

        # ===================================================================
        # FINAL SUMMARY
        # ===================================================================
        self.print_summary()

        # Write combined results to JSON file (includes original JSON outputs)
        self.write_combined_results()

        # Overall success: Phase 1 must pass (both Oracle and NOP tb_positive), Phase 2/3 tolerate failures
        oracle_result = self.results.get('oracle')
        nop_result = self.results.get('nop')

        oracle_tb_positive = oracle_result and oracle_result.result_type == 'tb_positive'
        nop_tb_positive = nop_result and nop_result.result_type == 'tb_positive'

        return oracle_tb_positive and nop_tb_positive

    def print_summary(self):
        """Print final summary of all results"""
        print(f"\n{'='*80}")
        print("FULL CHECK COMPLETE - SUMMARY")
        print(f"{'='*80}\n")

        # Phase 1
        print("Phase 1 (Oracle & NOP - fail-fast):")
        for name in ['oracle', 'nop']:
            if name in self.results:
                result = self.results[name]
                status = "✅ PASS" if result.success else "❌ FAIL"
                print(f"  {name:20} {status:10} ({result.duration:.1f}s)")
                if result.accuracy is not None:
                    acc_pct = result.accuracy * 100 if isinstance(result.accuracy, float) else (100 if result.accuracy else 0)
                    print(f"                       Accuracy: {acc_pct:.1f}%")
            elif name in self.cancelled_jobs:
                print(f"  {name:20} 🚫 CANCELLED")

        print()

        # Phase 2
        print("Phase 2 (TB Check & Runs - parallel):")
        for name in ['tb_check', 'tb_run_small', 'tb_run_large']:
            if name in self.results:
                result = self.results[name]
                status = "✅ PASS" if result.success else "❌ FAIL"
                print(f"  {name:20} {status:10} ({result.duration:.1f}s)")
                if result.accuracy is not None:
                    acc_pct = result.accuracy * 100 if isinstance(result.accuracy, float) else (100 if result.accuracy else 0)
                    print(f"                       Accuracy: {acc_pct:.1f}%")
                if result.min_commands is not None:
                    # Determine which threshold applies to this run
                    threshold = self.config.min_commands_threshold_small if name == 'tb_run_small' else self.config.min_commands_threshold_large
                    threshold_status = ""
                    if result.commands_threshold_met is not None and threshold > 0:
                        threshold_icon = "✅" if result.commands_threshold_met else "❌"
                        threshold_status = f" ({threshold_icon} >= {threshold})"
                    elif threshold == 0:
                        threshold_status = " (no threshold)"
                    print(f"                       Min Commands: {result.min_commands}{threshold_status}")

        print()

        # Phase 3
        print("Phase 3 (TB Debug - conditional):")
        for name in ['tb_debug_small', 'tb_debug_large']:
            if name in self.results:
                result = self.results[name]
                if "Skipped" in result.stderr:
                    print(f"  {name:20} ⏭️  SKIPPED  (accuracy = 100%)")
                else:
                    status = "✅ PASS" if result.success else "❌ FAIL"
                    print(f"  {name:20} {status:10} ({result.duration:.1f}s)")

        print(f"\n{'='*80}\n")

    def write_combined_results(self):
        """Write combined results from all jobs to a single JSON file"""
        combined_results = {
            "task_id": self.config.task_id,
            "tasks_dir": self.config.tasks_dir,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        # Add all results directly (no phase grouping)
        # ai_detect comes first, before oracle
        for name in ['ai_detect', 'oracle', 'nop', 'tb_check', 'tb_run_small', 'tb_run_large', 'tb_debug_small', 'tb_debug_large']:
            if name in self.results:
                result = self.results[name]
                result_data = {
                    "success": result.success,
                    "result_type": result.result_type,
                    "duration": result.duration,
                    "return_code": result.return_code
                }

                # Add accuracy for run commands
                if name in ['oracle', 'nop', 'tb_run_small', 'tb_run_large']:
                    result_data["accuracy"] = result.accuracy
                    # Add minimum commands for successful runs
                    if result.min_commands is not None:
                        result_data["min_commands"] = result.min_commands
                    # Add commands threshold status (only for TB_RUN, not oracle/nop)
                    if name in ['tb_run_small', 'tb_run_large'] and result.commands_threshold_met is not None:
                        result_data["commands_threshold_met"] = result.commands_threshold_met
                    # Add list of n_commands from successful attempts
                    if result.successful_n_commands is not None:
                        result_data["successful_n_commands"] = result.successful_n_commands

                # Add skipped flag for debug commands
                if name in ['tb_debug_small', 'tb_debug_large']:
                    result_data["skipped"] = "Skipped" in result.stderr

                # Add original JSON output if available
                if result.json_output:
                    result_data["original_result"] = result.json_output

                combined_results[name] = result_data
            elif name in self.cancelled_jobs:
                combined_results[name] = {
                    "success": False,
                    "result_type": "cancelled",
                    "duration": 0,
                    "accuracy": None if name in ['oracle', 'nop', 'tb_run_small', 'tb_run_large'] else None,
                    "return_code": -1
                }

        # Calculate overall success
        # Critical requirements for overall success:
        # 1. AI Detection must pass (result_type == 'tb_positive')
        # 2. Oracle must pass (result_type == 'tb_positive', accuracy == 100%)
        # 3. NOP must pass (result_type == 'tb_positive', accuracy == 0%)
        # 4. TB Check must pass (result_type == 'tb_positive')
        # 5. TB Debug must pass OR be skipped (result_type == 'tb_positive' OR skipped == True)
        # 6. TB Run Small must have accuracy < 100% (proves task is non-trivial)
        # 7. TB Run Large must have accuracy > 0% (proves frontier model can solve it)
        # 8. TB Run Small must meet commands threshold (all successful attempts >= 10 commands)

        ai_detect_success = combined_results.get('ai_detect', {}).get('result_type') == 'tb_positive'
        oracle_success = combined_results.get('oracle', {}).get('result_type') == 'tb_positive'
        nop_success = combined_results.get('nop', {}).get('result_type') == 'tb_positive'
        tb_check_success = combined_results.get('tb_check', {}).get('result_type') == 'tb_positive'

        # TB Debug is successful if it passes OR if it was skipped (skipped when accuracy = 100%)
        tb_debug_small_data = combined_results.get('tb_debug_small', {})
        tb_debug_small_success = (
            tb_debug_small_data.get('result_type') == 'tb_positive' or
            tb_debug_small_data.get('skipped', False)
        )

        tb_debug_large_data = combined_results.get('tb_debug_large', {})
        tb_debug_large_success = (
            tb_debug_large_data.get('result_type') == 'tb_positive' or
            tb_debug_large_data.get('skipped', False)
        )

        # TB Run checks: check accuracy thresholds directly (matches bot display logic in index.js:2317,2336)
        tb_run_small_data = combined_results.get('tb_run_small', {})
        tb_run_small_accuracy = tb_run_small_data.get('accuracy', 0)
        tb_run_small_success = tb_run_small_accuracy < 1.0  # Must be less than 100%
        # Also check commands threshold for small model
        tb_run_small_commands_ok = tb_run_small_data.get('commands_threshold_met', True)  # Default to True if not present

        tb_run_large_data = combined_results.get('tb_run_large', {})
        tb_run_large_accuracy = tb_run_large_data.get('accuracy', 0)
        tb_run_large_success = tb_run_large_accuracy > 0  # Must be greater than 0%

        # Overall success requires all critical checks to pass
        combined_results["overall_success"] = (ai_detect_success and oracle_success and nop_success and
                                               tb_check_success and tb_debug_small_success and tb_debug_large_success and
                                               tb_run_small_success and tb_run_large_success and tb_run_small_commands_ok)

        # Write to file in the run directory
        output_file = os.path.join(self.run_dir, 'full-check-result.json')

        with open(output_file, 'w') as f:
            json.dump(combined_results, f, indent=2)

        print(f"📄 Combined results written to: {output_file}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Run full check workflow locally (mimics bot full-check command)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage (uses defaults: terminus-2 agent with gpt-oss-120b and gpt-5)
  python full_check.py --task-id hello-world

  # Override default agents and models
  python full_check.py --task-id hello-world \\
      --tb-run-small-agent claude-code \\
      --tb-run-small-model claude-sonnet-3-5 \\
      --tb-run-large-agent claude-code \\
      --tb-run-large-model claude-sonnet-4-5

  # Custom paths
  python full_check.py --task-id my-task --tasks-dir custom_tasks
        """
    )

    # Task configuration
    parser.add_argument('--task-id', type=str, default=None,
                        help='Task ID to run (e.g., hello-world)')
    parser.add_argument('--tasks-dir', type=str, default='tasks',
                        help='Path to tasks directory (default: tasks)')
    parser.add_argument('--output-dir', type=str, default='runs/full-check',
                        help='Output directory for results (default: runs/full-check)')
    parser.add_argument('--skip-steps', type=str, nargs='*', default=[],
                        choices=['phase2', 'phase3', 'tb_check', 'tb_run_small', 'tb_run_large', 'tb_debug_small', 'tb_debug_large'],
                        help='Steps to skip (e.g., --skip-steps phase2 phase3 or --skip-steps tb_check)')

    # TB Run Small configuration
    parser.add_argument('--tb-run-small-agent', type=str, default='terminus-2',
                        help='Agent for small model run (default: terminus-2)')
    parser.add_argument('--tb-run-small-model', type=str, default='openrouter/openai/gpt-oss-120b',
                        help='Model for small model run (default: openrouter/openai/gpt-oss-120b)')
    parser.add_argument('--tb-run-small-n-attempts', type=int, default=5,
                        help='Number of attempts for small model (default: 5)')
    parser.add_argument('--tb-run-small-n-concurrent', type=int, default=5,
                        help='Number of concurrent runs for small model (default: 5)')
    parser.add_argument('--tb-run-small-use-subscription', action='store_true',
                        help='Use subscription for small model')

    # TB Run Large configuration
    parser.add_argument('--tb-run-large-agent', type=str, default='terminus-2',
                        help='Agent for large model run (default: terminus-2)')
    parser.add_argument('--tb-run-large-model', type=str, default='openrouter/openai/gpt-5',
                        help='Model for large model run (default: openrouter/openai/gpt-5)')
    parser.add_argument('--tb-run-large-n-attempts', type=int, default=3,
                        help='Number of attempts for large model (default: 3)')
    parser.add_argument('--tb-run-large-n-concurrent', type=int, default=3,
                        help='Number of concurrent runs for large model (default: 3)')
    parser.add_argument('--tb-run-large-use-subscription', action='store_true',
                        help='Use subscription for large model')

    # TB Check configuration
    parser.add_argument('--tb-check-agent', type=str, default=None,
                        help='Agent for TB check (default: None)')
    parser.add_argument('--tb-check-model', type=str, default='openrouter/openai/gpt-5',
                        help='Model for TB check (default: openrouter/openai/gpt-5)')

    # TB Debug configuration
    parser.add_argument('--tb-debug-agent', type=str, default=None,
                        help='Agent for TB debug (default: None)')
    parser.add_argument('--tb-debug-model', type=str, default='openrouter/openai/gpt-5',
                        help='Model for TB debug (default: openrouter/openai/gpt-5)')

    # Validation thresholds
    parser.add_argument('--min-commands-threshold-small', type=int, default=10,
                        help='Minimum terminal commands required for successful small model attempts (default: 10)')
    parser.add_argument('--min-commands-threshold-large', type=int, default=0,
                        help='Minimum terminal commands required for successful large model attempts (default: 0, no threshold)')

    args = parser.parse_args()

    # Create configuration
    config = FullCheckConfig(
        task_id=args.task_id,
        tasks_dir=args.tasks_dir,
        output_dir=args.output_dir,
        skip_steps=args.skip_steps,
        tb_run_small_agent=args.tb_run_small_agent,
        tb_run_small_model=args.tb_run_small_model,
        tb_run_small_n_attempts=args.tb_run_small_n_attempts,
        tb_run_small_n_concurrent=args.tb_run_small_n_concurrent,
        tb_run_small_use_subscription=args.tb_run_small_use_subscription,
        tb_run_large_agent=args.tb_run_large_agent,
        tb_run_large_model=args.tb_run_large_model,
        tb_run_large_n_attempts=args.tb_run_large_n_attempts,
        tb_run_large_n_concurrent=args.tb_run_large_n_concurrent,
        tb_run_large_use_subscription=args.tb_run_large_use_subscription,
        tb_check_agent=args.tb_check_agent,
        tb_check_model=args.tb_check_model,
        tb_debug_agent=args.tb_debug_agent,
        tb_debug_model=args.tb_debug_model,
        min_commands_threshold_small=args.min_commands_threshold_small,
        min_commands_threshold_large=args.min_commands_threshold_large
    )

    # Create runner and execute
    runner = FullCheckRunner(config)

    try:
        success = asyncio.run(runner.run_full_check())
        # Always exit with 0 for completed checks (even if checks failed)
        # Non-zero exit codes are reserved for system errors (exceptions below)
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\n❌ Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
