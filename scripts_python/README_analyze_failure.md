# Task Failure Analysis Script

## Purpose
Analyzes failed Terminal-Bench tasks by examining agent recordings and test logs to diagnose why tasks failed.

## Requirements
- Python 3.8+
- OpenAI API key (provided via --api-key argument or OPENAI_API_KEY environment variable)
- Access to GPT-5 model

## Usage

```bash
# Analyze the first failed task in results (with API key as argument)
python scripts_python/analyze_task_failure.py /path/to/results.json --api-key YOUR_API_KEY

# Analyze the first failed task in results (with env var)
export OPENAI_API_KEY="your-api-key"
python scripts_python/analyze_task_failure.py /path/to/results.json

# Analyze multiple failed trials (up to 3)
python scripts_python/analyze_task_failure.py /path/to/results.json -n 3 --api-key YOUR_API_KEY

# Analyze a specific task
python scripts_python/analyze_task_failure.py /path/to/results.json --task-id ssh-auth --api-key YOUR_API_KEY

# Analyze multiple trials of a specific task
python scripts_python/analyze_task_failure.py /path/to/results.json --task-id ssh-auth -n 5 --api-key YOUR_API_KEY

# Save diagnosis to file
python scripts_python/analyze_task_failure.py /path/to/results.json --output diagnosis.txt --api-key YOUR_API_KEY
```

## Example

```bash
# Analyze single trial with command line argument
python scripts_python/analyze_task_failure.py runs/claude4_20251003_080007/results.json --task-id ssh-auth --api-key sk-...

# Analyze 3 trials with environment variable
export OPENAI_API_KEY="your-api-key"
python scripts_python/analyze_task_failure.py runs/claude4_20251003_080007/results.json --task-id ssh-auth -n 3

# Analyze all failed tasks (up to 10) and save to file
python scripts_python/analyze_task_failure.py runs/claude4_20251003_080007/results.json -n 10 --output detailed_analysis.txt --api-key sk-...
```

## Output
The script provides a comprehensive analysis including:

### Console Output:
- Task and trial information
- Test results summary (✓/✗ for each test)
- Agent command examples (first 10 commands)
- Relevant test output excerpts
- Detailed GPT-5 diagnosis

### Detailed Diagnosis:
1. **What the agent did** - 5-8 detailed bullet points explaining key actions with specific command examples and their intended purpose
2. **Why it failed** - 4-6 detailed bullet points explaining specific failure reasons, referencing exact test names and what they check
3. **What was missing** - 3-5 detailed bullet points describing missing actions, including specific commands and configuration steps
4. **Key problematic commands/actions** - 3-5 specific commands or lack thereof that directly contributed to failure

### File Output (if --output specified):
- Complete analysis with all agent commands (up to 30)
- Full relevant test output
- Structured diagnosis sections

## How it Works
1. Parses the results.json file to find failed tasks
2. Extracts agent commands from the .cast recording files
3. Parses test output to understand test failures
4. Uses GPT-5 to analyze the failure and generate a diagnosis