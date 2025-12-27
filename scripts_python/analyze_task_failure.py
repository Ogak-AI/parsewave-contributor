#!/usr/bin/env python3

import json
import argparse
import re
from pathlib import Path
from typing import Any
import openai
import os
from datetime import datetime


def parse_asciicast(cast_path: Path) -> list[dict[str, Any]]:
    """Parse asciicast file to extract commands and outputs."""
    events = []
    
    if not cast_path.exists():
        return events
    
    with open(cast_path, 'r') as f:
        lines = f.readlines()
    
    # Skip header
    for line in lines[1:]:
        try:
            event = json.loads(line)
            if len(event) >= 3:
                timestamp, event_type, data = event[0], event[1], event[2]
                if event_type in ['i', 'o']:  # input or output
                    events.append({
                        'timestamp': timestamp,
                        'type': 'input' if event_type == 'i' else 'output',
                        'data': data
                    })
        except json.JSONDecodeError:
            continue
    
    return events


def extract_agent_actions(events: list[dict[str, Any]]) -> list[str]:
    """Extract commands from agent recording."""
    actions = []
    current_command = ""
    
    for event in events:
        if event['type'] == 'input':
            data = event['data']
            # Check for command endings (both \r and \n)
            if '\r' in data or '\n' in data:
                # Add any remaining data before the line ending
                if '\r' in data:
                    current_command += data.split('\r')[0]
                elif '\n' in data:
                    current_command += data.split('\n')[0]
                
                if current_command:
                    # Clean ANSI codes and control characters
                    clean_cmd = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', current_command)
                    clean_cmd = clean_cmd.strip()
                    if clean_cmd and not clean_cmd.startswith('#'):
                        actions.append(clean_cmd)
                current_command = ""
            else:
                current_command += data
    
    return actions


def extract_test_output(events: list[dict[str, Any]]) -> str:
    """Extract test output from test recording."""
    output = ""
    for event in events:
        if event['type'] == 'output':
            # Clean ANSI codes
            clean_data = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', event['data'])
            output += clean_data
    
    return output


def format_diagnosis(diagnosis: str) -> str:
    """Format the diagnosis with better visual separation and highlighting."""
    lines = diagnosis.split('\n')
    formatted_lines = []
    current_section = ""
    section_count = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            formatted_lines.append("")
            continue
            
        # Check for main section headers
        if line.startswith('**') and line.endswith('**'):
            section_title = line.replace('**', '').strip()
            section_count += 1
            if section_count == 1:
                formatted_lines.append(f"\n🎯 {section_title.upper()}")
                formatted_lines.append("┅" * 60)
            elif section_count == 2:
                formatted_lines.append(f"\n❌ {section_title.upper()}")
                formatted_lines.append("┅" * 60)
            current_section = section_title.lower()
            continue
        
        # Check for numbered sections
        if line.startswith(('1)', '2)', '1.', '2.')):
            section_title = line[2:].strip().replace('**', '')
            section_count += 1
            if section_count == 1:
                formatted_lines.append(f"\n🎯 {section_title.upper()}")
                formatted_lines.append("┅" * 60)
            elif section_count == 2:
                formatted_lines.append(f"\n❌ {section_title.upper()}")
                formatted_lines.append("┅" * 60)
            current_section = section_title.lower()
            continue
            
        # Format bullet points
        if line.startswith('-'):
            bullet_text = line[1:].strip()
            # Try to extract and highlight command examples
            import re
            # Look for command patterns in backticks
            command_pattern = r'`([^`]+)`'
            
            def highlight_command(match):
                cmd = match.group(1)
                return f"\n    💻 {cmd}"
            
            # Check if there are backtick commands
            if '`' in bullet_text:
                # Split text and commands
                parts = re.split(command_pattern, bullet_text)
                formatted_text = ""
                for i, part in enumerate(parts):
                    if i % 2 == 0:  # Regular text
                        if part.strip():
                            formatted_text += part
                    else:  # Command
                        formatted_text += f"\n    💻 {part}"
                formatted_lines.append(f"\n  • {formatted_text.strip()}")
            else:
                formatted_lines.append(f"\n  • {bullet_text}")
            formatted_lines.append("")  # Add spacing between bullet points
        else:
            # Regular text
            if line:
                formatted_lines.append(f"    {line}")
    
    return '\n'.join(formatted_lines)


def analyze_with_gpt5(task_info: dict, agent_actions: list[str], test_output: str, api_key: str = None) -> tuple[str, list[str], str]:
    """Use GPT-5 to analyze the failure and return diagnosis with relevant examples."""
    
    # Get API key from argument or environment
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ("Error: OpenAI API key not provided. Use --api-key or set OPENAI_API_KEY environment variable", [], "")
    
    client = openai.OpenAI(api_key=api_key)
    
    # Extract relevant test failure lines
    test_lines = test_output.split('\n')
    failure_lines = []
    for i, line in enumerate(test_lines):
        if 'FAILED' in line or 'ERROR' in line or 'AssertionError' in line or 'test_' in line:
            # Get context around failure
            start = max(0, i-2)
            end = min(len(test_lines), i+3)
            failure_lines.extend(test_lines[start:end])
    
    relevant_test_output = '\n'.join(failure_lines[-100:]) if failure_lines else test_output[-3000:]
    
    prompt = f"""Analyze this Terminal-Bench task failure and provide a detailed diagnosis.

Task: {task_info['task_id']}
Instruction: {task_info['instruction']}

Test Results:
{json.dumps(task_info['parser_results'], indent=2)}

Agent Actions (commands executed):
{chr(10).join(f"- {action}" for action in agent_actions[:50])}  # Limit to first 50 actions

Test Output (relevant portions):
{relevant_test_output}

Please provide a DETAILED analysis with ONLY these 2 sections:

1. **What the agent did** - Provide 5-8 bullet points explaining the key actions taken, with specific command examples and their intended purpose. Each bullet should be 1-2 sentences explaining what was attempted and why. Include the actual commands in backticks.

2. **Why it failed** - Provide 4-6 detailed bullet points explaining the specific reasons for failure. Reference exact test names that failed, explain what each failing test was checking for, and connect it to missing or incorrect agent actions. Each bullet should be 1-2 sentences with specific details.

Do NOT include any other sections like "What was missing" or "Key problematic commands". Only provide the two sections above.

Be specific and technical. Reference actual command names, file paths, configuration directives, and test names where relevant."""

    try:
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {"role": "system", "content": "You are an expert at analyzing Terminal-Bench task failures. Provide clear, concise diagnoses with specific examples."},
                {"role": "user", "content": prompt}
            ],
        )
        
        diagnosis = response.choices[0].message.content
        
        # Return diagnosis along with relevant examples
        return (diagnosis, agent_actions[:20], relevant_test_output)
    except Exception as e:
        return (f"Error calling GPT-5: {str(e)}", [], "")


def main():
    parser = argparse.ArgumentParser(description="Analyze failed Terminal-Bench tasks")
    parser.add_argument("results_file", help="Path to results.json file")
    parser.add_argument("--task-id", help="Specific task ID to analyze (optional)")
    parser.add_argument("--output", help="Output file for diagnosis (optional)")
    parser.add_argument("--api-key", help="OpenAI API key (optional, can also use OPENAI_API_KEY env var)")
    parser.add_argument("-n", "--max-trials", type=int, default=1, help="Maximum number of failed trials to analyze (default: 1)")
    args = parser.parse_args()
    
    # Load results
    results_path = Path(args.results_file)
    if not results_path.exists():
        print(f"Error: Results file {results_path} not found")
        return 1
    
    with open(results_path, 'r') as f:
        data = json.load(f)
    
    # Find failed tasks
    failed_tasks = [r for r in data['results'] if not r['is_resolved']]
    
    if not failed_tasks:
        print("No failed tasks found in results")
        return 0
    
    # Filter by task_id if specified
    if args.task_id:
        failed_tasks = [t for t in failed_tasks if t['task_id'] == args.task_id]
        if not failed_tasks:
            print(f"No failed tasks found for task_id: {args.task_id}")
            return 1
    
    # Limit to max_trials
    tasks_to_analyze = failed_tasks[:args.max_trials]
    
    print(f"\nAnalyzing {len(tasks_to_analyze)} failed trial(s) out of {len(failed_tasks)} total failed tasks")
    
    # Initialize output file if specified
    output_content = []
    if args.output:
        output_content.append(f"Task Failure Analysis")
        output_content.append(f"{'='*60}")
        output_content.append(f"Generated: {datetime.now().isoformat()}")
        output_content.append(f"Analyzed {len(tasks_to_analyze)} trial(s) out of {len(failed_tasks)} total failed tasks\n")
    
    # Analyze each failed task
    for trial_idx, task in enumerate(tasks_to_analyze, 1):
        print(f"\n{'🔥' * 40}")
        print(f"🚨 TRIAL {trial_idx}/{len(tasks_to_analyze)}: {task['task_id']}")
        print(f"📋 {task['trial_name']}")
        print(f"{'🔥' * 40}\n")
        
        # Build paths
        base_dir = results_path.parent
        trial_dir = base_dir / task['task_id'] / task['trial_name']
        agent_cast = trial_dir / "sessions" / "agent.cast"
        test_cast = trial_dir / "sessions" / "tests.cast"
        
        # Parse recordings
        print("Parsing agent recording...")
        agent_events = parse_asciicast(agent_cast)
        agent_actions = extract_agent_actions(agent_events)
        
        print(f"Found {len(agent_actions)} agent commands")
        
        # Error handling for missing agent commands
        if len(agent_actions) == 0:
            print(f"ERROR: No agent commands found in {agent_cast}")
            print("This could indicate:")
            print("- Agent recording file is corrupted or incomplete")
            print("- Agent failed to execute any commands")
            print("- Parsing logic needs adjustment for this recording format")
            if not agent_cast.exists():
                print(f"- Agent recording file does not exist: {agent_cast}")
            else:
                print(f"- Agent recording file exists but may be empty or malformed")
                # Show first few lines for debugging
                try:
                    with open(agent_cast, 'r') as f:
                        first_lines = [f.readline().strip() for _ in range(5)]
                    print("First 5 lines of agent recording:")
                    for i, line in enumerate(first_lines, 1):
                        print(f"  {i}: {line}")
                except Exception as e:
                    print(f"Could not read agent recording: {e}")
            continue  # Skip this trial
        
        print("Parsing test recording...")
        test_events = parse_asciicast(test_cast)
        test_output = extract_test_output(test_events)
        
        # Analyze with GPT-5
        print("\nAnalyzing with GPT-5...")
        diagnosis, example_commands, relevant_test = analyze_with_gpt5(task, agent_actions, test_output, args.api_key)
        
        # Output results with prettier formatting
        print("\n" + "█" * 80)
        print("🔍 TASK FAILURE ANALYSIS")
        print("█" * 80)
        print(f"\n📋 Task ID: {task['task_id']}")
        print(f"🏃 Trial: {task['trial_name']}")
        print(f"\n📊 Test Results Summary:")
        for test_name, result in task['parser_results'].items():
            if result == "passed":
                print(f"  ✅ {test_name}")
            else:
                print(f"  ❌ {test_name}")
        
        print("\n" + "─" * 80)
        print("💻 AGENT COMMAND EXAMPLES")
        print("─" * 80)
        print("📝 First commands executed by the agent:")
        for i, cmd in enumerate(example_commands[:10], 1):
            print(f"  {i:2}. 💾 {cmd}")
        
        if relevant_test:
            print("\n" + "─" * 80)
            print("🧪 RELEVANT TEST OUTPUT")
            print("─" * 80)
            # Format test output with indentation
            test_lines = relevant_test[:1500].split('\n')
            for line in test_lines:
                if line.strip():
                    print(f"   📄 {line}")
        
        print("\n" + "═" * 80)
        print("🔬 DETAILED DIAGNOSIS")
        print("═" * 80)
        
        # Format the diagnosis with better visual separation
        formatted_diagnosis = format_diagnosis(diagnosis)
        print(formatted_diagnosis)
        
        # Add to output file content if specified
        if args.output:
            output_content.append(f"\n{'='*80}")
            output_content.append(f"TRIAL {trial_idx}/{len(tasks_to_analyze)}: {task['task_id']}")
            output_content.append(f"Trial: {task['trial_name']}")
            output_content.append(f"{'='*80}\n")
            
            output_content.append(f"Test Results:")
            output_content.append(json.dumps(task['parser_results'], indent=2))
            
            output_content.append(f"\n\n{'='*60}")
            output_content.append(f"AGENT COMMAND EXAMPLES")
            output_content.append(f"{'='*60}")
            output_content.append("Commands executed by the agent:")
            for i, action in enumerate(agent_actions[:30], 1):
                output_content.append(f"  {i:2}. {action}")
            
            if relevant_test:
                output_content.append(f"\n{'='*60}")
                output_content.append(f"RELEVANT TEST OUTPUT")
                output_content.append(f"{'='*60}")
                output_content.append(relevant_test)
            
            output_content.append(f"\n\n{'='*60}")
            output_content.append(f"DIAGNOSIS")
            output_content.append(f"{'='*60}")
            output_content.append(diagnosis)
    
    # Save to file if specified
    if args.output:
        output_path = Path(args.output)
        with open(output_path, 'w') as f:
            f.write('\n'.join(output_content))
        print(f"\n{'='*60}")
        print(f"Analysis of {len(tasks_to_analyze)} trial(s) saved to: {output_path}")
    
    return 0


if __name__ == "__main__":
    exit(main())
#!/usr/bin/env python3

import json
import argparse
import re
from pathlib import Path
from typing import Any
import openai
import os
from datetime import datetime


def parse_asciicast(cast_path: Path) -> list[dict[str, Any]]:
    """Parse asciicast file to extract commands and outputs."""
    events = []
    
    if not cast_path.exists():
        return events
    
    with open(cast_path, 'r') as f:
        lines = f.readlines()
    
    # Skip header
    for line in lines[1:]:
        try:
            event = json.loads(line)
            if len(event) >= 3:
                timestamp, event_type, data = event[0], event[1], event[2]
                if event_type in ['i', 'o']:  # input or output
                    events.append({
                        'timestamp': timestamp,
                        'type': 'input' if event_type == 'i' else 'output',
                        'data': data
                    })
        except json.JSONDecodeError:
            continue
    
    return events


def extract_agent_actions(events: list[dict[str, Any]]) -> list[str]:
    """Extract commands from agent recording."""
    actions = []
    current_command = ""
    
    for event in events:
        if event['type'] == 'input':
            data = event['data']
            # Check for command endings (both \r and \n)
            if '\r' in data or '\n' in data:
                # Add any remaining data before the line ending
                if '\r' in data:
                    current_command += data.split('\r')[0]
                elif '\n' in data:
                    current_command += data.split('\n')[0]
                
                if current_command:
                    # Clean ANSI codes and control characters
                    clean_cmd = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', current_command)
                    clean_cmd = clean_cmd.strip()
                    if clean_cmd and not clean_cmd.startswith('#'):
                        actions.append(clean_cmd)
                current_command = ""
            else:
                current_command += data
    
    return actions


def extract_test_output(events: list[dict[str, Any]]) -> str:
    """Extract test output from test recording."""
    output = ""
    for event in events:
        if event['type'] == 'output':
            # Clean ANSI codes
            clean_data = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', event['data'])
            output += clean_data
    
    return output


def format_diagnosis(diagnosis: str) -> str:
    """Format the diagnosis with better visual separation and highlighting."""
    lines = diagnosis.split('\n')
    formatted_lines = []
    current_section = ""
    section_count = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            formatted_lines.append("")
            continue
            
        # Check for main section headers
        if line.startswith('**') and line.endswith('**'):
            section_title = line.replace('**', '').strip()
            section_count += 1
            if section_count == 1:
                formatted_lines.append(f"\n🎯 {section_title.upper()}")
                formatted_lines.append("┅" * 60)
            elif section_count == 2:
                formatted_lines.append(f"\n❌ {section_title.upper()}")
                formatted_lines.append("┅" * 60)
            current_section = section_title.lower()
            continue
        
        # Check for numbered sections
        if line.startswith(('1)', '2)', '1.', '2.')):
            section_title = line[2:].strip().replace('**', '')
            section_count += 1
            if section_count == 1:
                formatted_lines.append(f"\n🎯 {section_title.upper()}")
                formatted_lines.append("┅" * 60)
            elif section_count == 2:
                formatted_lines.append(f"\n❌ {section_title.upper()}")
                formatted_lines.append("┅" * 60)
            current_section = section_title.lower()
            continue
            
        # Format bullet points
        if line.startswith('-'):
            bullet_text = line[1:].strip()
            # Try to extract and highlight command examples
            import re
            # Look for command patterns in backticks
            command_pattern = r'`([^`]+)`'
            
            def highlight_command(match):
                cmd = match.group(1)
                return f"\n    💻 {cmd}"
            
            # Check if there are backtick commands
            if '`' in bullet_text:
                # Split text and commands
                parts = re.split(command_pattern, bullet_text)
                formatted_text = ""
                for i, part in enumerate(parts):
                    if i % 2 == 0:  # Regular text
                        if part.strip():
                            formatted_text += part
                    else:  # Command
                        formatted_text += f"\n    💻 {part}"
                formatted_lines.append(f"\n  • {formatted_text.strip()}")
            else:
                formatted_lines.append(f"\n  • {bullet_text}")
            formatted_lines.append("")  # Add spacing between bullet points
        else:
            # Regular text
            if line:
                formatted_lines.append(f"    {line}")
    
    return '\n'.join(formatted_lines)


def analyze_with_gpt5(task_info: dict, agent_actions: list[str], test_output: str, api_key: str = None) -> tuple[str, list[str], str]:
    """Use GPT-5 to analyze the failure and return diagnosis with relevant examples."""
    
    # Get API key from argument or environment
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ("Error: OpenAI API key not provided. Use --api-key or set OPENAI_API_KEY environment variable", [], "")
    
    client = openai.OpenAI(api_key=api_key)
    
    # Extract relevant test failure lines
    test_lines = test_output.split('\n')
    failure_lines = []
    for i, line in enumerate(test_lines):
        if 'FAILED' in line or 'ERROR' in line or 'AssertionError' in line or 'test_' in line:
            # Get context around failure
            start = max(0, i-2)
            end = min(len(test_lines), i+3)
            failure_lines.extend(test_lines[start:end])
    
    relevant_test_output = '\n'.join(failure_lines[-100:]) if failure_lines else test_output[-3000:]
    
    prompt = f"""Analyze this Terminal-Bench task failure and provide a detailed diagnosis.

Task: {task_info['task_id']}
Instruction: {task_info['instruction']}

Test Results:
{json.dumps(task_info['parser_results'], indent=2)}

Agent Actions (commands executed):
{chr(10).join(f"- {action}" for action in agent_actions[:50])}  # Limit to first 50 actions

Test Output (relevant portions):
{relevant_test_output}

Please provide a DETAILED analysis with ONLY these 2 sections:

1. **What the agent did** - Provide 5-8 bullet points explaining the key actions taken, with specific command examples and their intended purpose. Each bullet should be 1-2 sentences explaining what was attempted and why. Include the actual commands in backticks.

2. **Why it failed** - Provide 4-6 detailed bullet points explaining the specific reasons for failure. Reference exact test names that failed, explain what each failing test was checking for, and connect it to missing or incorrect agent actions. Each bullet should be 1-2 sentences with specific details.

Do NOT include any other sections like "What was missing" or "Key problematic commands". Only provide the two sections above.

Be specific and technical. Reference actual command names, file paths, configuration directives, and test names where relevant."""

    try:
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {"role": "system", "content": "You are an expert at analyzing Terminal-Bench task failures. Provide clear, concise diagnoses with specific examples."},
                {"role": "user", "content": prompt}
            ],
        )
        
        diagnosis = response.choices[0].message.content
        
        # Return diagnosis along with relevant examples
        return (diagnosis, agent_actions[:20], relevant_test_output)
    except Exception as e:
        return (f"Error calling GPT-5: {str(e)}", [], "")


def main():
    parser = argparse.ArgumentParser(description="Analyze failed Terminal-Bench tasks")
    parser.add_argument("results_file", help="Path to results.json file")
    parser.add_argument("--task-id", help="Specific task ID to analyze (optional)")
    parser.add_argument("--output", help="Output file for diagnosis (optional)")
    parser.add_argument("--api-key", help="OpenAI API key (optional, can also use OPENAI_API_KEY env var)")
    parser.add_argument("-n", "--max-trials", type=int, default=1, help="Maximum number of failed trials to analyze (default: 1)")
    args = parser.parse_args()
    
    # Load results
    results_path = Path(args.results_file)
    if not results_path.exists():
        print(f"Error: Results file {results_path} not found")
        return 1
    
    with open(results_path, 'r') as f:
        data = json.load(f)
    
    # Find failed tasks
    failed_tasks = [r for r in data['results'] if not r['is_resolved']]
    
    if not failed_tasks:
        print("No failed tasks found in results")
        return 0
    
    # Filter by task_id if specified
    if args.task_id:
        failed_tasks = [t for t in failed_tasks if t['task_id'] == args.task_id]
        if not failed_tasks:
            print(f"No failed tasks found for task_id: {args.task_id}")
            return 1
    
    # Limit to max_trials
    tasks_to_analyze = failed_tasks[:args.max_trials]
    
    print(f"\nAnalyzing {len(tasks_to_analyze)} failed trial(s) out of {len(failed_tasks)} total failed tasks")
    
    # Initialize output file if specified
    output_content = []
    if args.output:
        output_content.append(f"Task Failure Analysis")
        output_content.append(f"{'='*60}")
        output_content.append(f"Generated: {datetime.now().isoformat()}")
        output_content.append(f"Analyzed {len(tasks_to_analyze)} trial(s) out of {len(failed_tasks)} total failed tasks\n")
    
    # Analyze each failed task
    for trial_idx, task in enumerate(tasks_to_analyze, 1):
        print(f"\n{'🔥' * 40}")
        print(f"🚨 TRIAL {trial_idx}/{len(tasks_to_analyze)}: {task['task_id']}")
        print(f"📋 {task['trial_name']}")
        print(f"{'🔥' * 40}\n")
        
        # Build paths
        base_dir = results_path.parent
        trial_dir = base_dir / task['task_id'] / task['trial_name']
        agent_cast = trial_dir / "sessions" / "agent.cast"
        test_cast = trial_dir / "sessions" / "tests.cast"
        
        # Parse recordings
        print("Parsing agent recording...")
        agent_events = parse_asciicast(agent_cast)
        agent_actions = extract_agent_actions(agent_events)
        
        print(f"Found {len(agent_actions)} agent commands")
        
        # Error handling for missing agent commands
        if len(agent_actions) == 0:
            print(f"ERROR: No agent commands found in {agent_cast}")
            print("This could indicate:")
            print("- Agent recording file is corrupted or incomplete")
            print("- Agent failed to execute any commands")
            print("- Parsing logic needs adjustment for this recording format")
            if not agent_cast.exists():
                print(f"- Agent recording file does not exist: {agent_cast}")
            else:
                print(f"- Agent recording file exists but may be empty or malformed")
                # Show first few lines for debugging
                try:
                    with open(agent_cast, 'r') as f:
                        first_lines = [f.readline().strip() for _ in range(5)]
                    print("First 5 lines of agent recording:")
                    for i, line in enumerate(first_lines, 1):
                        print(f"  {i}: {line}")
                except Exception as e:
                    print(f"Could not read agent recording: {e}")
            continue  # Skip this trial
        
        print("Parsing test recording...")
        test_events = parse_asciicast(test_cast)
        test_output = extract_test_output(test_events)
        
        # Analyze with GPT-5
        print("\nAnalyzing with GPT-5...")
        diagnosis, example_commands, relevant_test = analyze_with_gpt5(task, agent_actions, test_output, args.api_key)
        
        # Output results with prettier formatting
        print("\n" + "█" * 80)
        print("🔍 TASK FAILURE ANALYSIS")
        print("█" * 80)
        print(f"\n📋 Task ID: {task['task_id']}")
        print(f"🏃 Trial: {task['trial_name']}")
        print(f"\n📊 Test Results Summary:")
        for test_name, result in task['parser_results'].items():
            if result == "passed":
                print(f"  ✅ {test_name}")
            else:
                print(f"  ❌ {test_name}")
        
        print("\n" + "─" * 80)
        print("💻 AGENT COMMAND EXAMPLES")
        print("─" * 80)
        print("📝 First commands executed by the agent:")
        for i, cmd in enumerate(example_commands[:10], 1):
            print(f"  {i:2}. 💾 {cmd}")
        
        if relevant_test:
            print("\n" + "─" * 80)
            print("🧪 RELEVANT TEST OUTPUT")
            print("─" * 80)
            # Format test output with indentation
            test_lines = relevant_test[:1500].split('\n')
            for line in test_lines:
                if line.strip():
                    print(f"   📄 {line}")
        
        print("\n" + "═" * 80)
        print("🔬 DETAILED DIAGNOSIS")
        print("═" * 80)
        
        # Format the diagnosis with better visual separation
        formatted_diagnosis = format_diagnosis(diagnosis)
        print(formatted_diagnosis)
        
        # Add to output file content if specified
        if args.output:
            output_content.append(f"\n{'='*80}")
            output_content.append(f"TRIAL {trial_idx}/{len(tasks_to_analyze)}: {task['task_id']}")
            output_content.append(f"Trial: {task['trial_name']}")
            output_content.append(f"{'='*80}\n")
            
            output_content.append(f"Test Results:")
            output_content.append(json.dumps(task['parser_results'], indent=2))
            
            output_content.append(f"\n\n{'='*60}")
            output_content.append(f"AGENT COMMAND EXAMPLES")
            output_content.append(f"{'='*60}")
            output_content.append("Commands executed by the agent:")
            for i, action in enumerate(agent_actions[:30], 1):
                output_content.append(f"  {i:2}. {action}")
            
            if relevant_test:
                output_content.append(f"\n{'='*60}")
                output_content.append(f"RELEVANT TEST OUTPUT")
                output_content.append(f"{'='*60}")
                output_content.append(relevant_test)
            
            output_content.append(f"\n\n{'='*60}")
            output_content.append(f"DIAGNOSIS")
            output_content.append(f"{'='*60}")
            output_content.append(diagnosis)
    
    # Save to file if specified
    if args.output:
        output_path = Path(args.output)
        with open(output_path, 'w') as f:
            f.write('\n'.join(output_content))
        print(f"\n{'='*60}")
        print(f"Analysis of {len(tasks_to_analyze)} trial(s) saved to: {output_path}")
    
    return 0


if __name__ == "__main__":
    exit(main())