#!/bin/bash
# Script to run multiple models on the local dataset

DATASET_PATH="./our_tasks"
N_ATTEMPTS=5
OPENAI_KEY=""
ANTHROPIC_KEY=""
GEMINI_KEY=""
OPENROUTER_KEY=""
DATASET_NAME=""
REGISTRY_FILE="registry.json"
TASK_TYPE="cli"  # Default to cli
CREDENTIALS_FILE=".credentials.yaml"

# Load credentials from .credentials.yaml if it exists
if [[ -f "$CREDENTIALS_FILE" ]]; then
    echo "Loading credentials from $CREDENTIALS_FILE"
    if command -v yq &> /dev/null; then
        # Use yq if available (more robust)
        OPENAI_KEY=$(yq -r '.OPENAI_API_KEY // empty' "$CREDENTIALS_FILE")
        ANTHROPIC_KEY=$(yq -r '.ANTHROPIC_API_KEY // empty' "$CREDENTIALS_FILE")
        GEMINI_KEY=$(yq -r '.GEMINI_API_KEY // empty' "$CREDENTIALS_FILE")
        OPENROUTER_KEY=$(yq -r '.OPENROUTER_API_KEY // empty' "$CREDENTIALS_FILE")
    else
        # Fallback to python if yq is not available
        OPENAI_KEY=$(python3 -c "import yaml; data=yaml.safe_load(open('$CREDENTIALS_FILE')); print(data.get('OPENAI_API_KEY', ''))" 2>/dev/null)
        ANTHROPIC_KEY=$(python3 -c "import yaml; data=yaml.safe_load(open('$CREDENTIALS_FILE')); print(data.get('ANTHROPIC_API_KEY', ''))" 2>/dev/null)
        GEMINI_KEY=$(python3 -c "import yaml; data=yaml.safe_load(open('$CREDENTIALS_FILE')); print(data.get('GEMINI_API_KEY', ''))" 2>/dev/null)
        OPENROUTER_KEY=$(python3 -c "import yaml; data=yaml.safe_load(open('$CREDENTIALS_FILE')); print(data.get('OPENROUTER_API_KEY', ''))" 2>/dev/null)
    fi
fi

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            echo "Usage: $0 --dataset DATASET_NAME [OPTIONS]"
            echo ""
            echo "API keys are loaded from .credentials.yaml by default if the file exists."
            echo "Command-line arguments will override credentials from the file."
            echo ""
            echo "Required arguments:"
            echo "  --dataset DATASET_NAME    Name of dataset from registry.json"
            echo ""
            echo "Optional arguments:"
            echo "  --task-type cli|code      Task type (default: cli)"
            echo "  --n-attempts N            Number of attempts per model (default: 5)"
            echo "  --openai-key KEY          OpenAI API key (overrides .credentials.yaml)"
            echo "  --anthropic-key KEY       Anthropic API key (overrides .credentials.yaml)"
            echo "  --gemini-key KEY          Google Gemini API key (overrides .credentials.yaml)"
            echo "  --openrouter-key KEY      OpenRouter API key (overrides .credentials.yaml)"
            echo ""
            echo "Example:"
            echo "  $0 --dataset pw-python-completion --task-type code"
            echo ""
            echo "Note: LiteLLM automatically selects the correct API key based on the model prefix:"
            echo "  - anthropic/* uses ANTHROPIC_API_KEY"
            echo "  - openai/* uses OPENAI_API_KEY"
            echo "  - openrouter/* uses OPENROUTER_API_KEY"
            echo "  - gemini/* uses GEMINI_API_KEY"
            exit 0
            ;;
        --task-type)
            TASK_TYPE="$2"
            shift 2
            ;;
        --n-attempts)
            N_ATTEMPTS="$2"
            shift 2
            ;;
        --openai-key)
            OPENAI_KEY="$2"
            shift 2
            ;;
        --anthropic-key)
            ANTHROPIC_KEY="$2"
            shift 2
            ;;
        --gemini-key)
            GEMINI_KEY="$2"
            shift 2
            ;;
        --openrouter-key)
            OPENROUTER_KEY="$2"
            shift 2
            ;;
        --dataset)
            DATASET_NAME="$2"
            shift 2
            ;;
        *)
            echo "Unknown option $1"
            echo "Usage: $0 --dataset DATASET_NAME [--task-type cli|code] [--n-attempts N] [--openai-key KEY] [--anthropic-key KEY] [--gemini-key KEY] [--openrouter-key KEY]"
            echo ""
            echo "Run '$0 --help' for more information."
            exit 1
            ;;
    esac
done

# Check if dataset name is provided
if [[ -z "$DATASET_NAME" ]]; then
    echo "Error: --dataset is required"
    echo "Available datasets in $REGISTRY_FILE:"
    if [[ -f "$REGISTRY_FILE" ]]; then
        python3 -c "import json; data=json.load(open('$REGISTRY_FILE')); [print(f'  - {d[\"name\"]}') for d in data]"
    fi
    exit 1
fi

# Validate task type
if [[ "$TASK_TYPE" != "cli" && "$TASK_TYPE" != "code" ]]; then
    echo "Error: Invalid task-type '$TASK_TYPE'. Must be 'cli' or 'code'"
    exit 1
fi

# Extract task IDs from registry for the dataset
TASK_ARGS=()
if [[ -f "$REGISTRY_FILE" ]]; then
    TASK_IDS=$(python3 -c "
import json
data = json.load(open('$REGISTRY_FILE'))
for d in data:
    if d['name'] == '$DATASET_NAME':
        for task in d.get('task_id_subset', []):
            print(task)
")
    if [[ -z "$TASK_IDS" ]]; then
        echo "Error: Dataset '$DATASET_NAME' not found in $REGISTRY_FILE or has no tasks"
        exit 1
    fi
    
    # Convert task IDs to array arguments
    while IFS= read -r task_id; do
        TASK_ARGS+=("--task-id" "$task_id")
    done <<< "$TASK_IDS"
else
    echo "Error: Registry file '$REGISTRY_FILE' not found"
    exit 1
fi

# Set API keys as environment variables if provided
if [[ -n "$OPENAI_KEY" ]]; then
    export OPENAI_API_KEY="$OPENAI_KEY"
fi
if [[ -n "$ANTHROPIC_KEY" ]]; then
    export ANTHROPIC_API_KEY="$ANTHROPIC_KEY"
fi
if [[ -n "$GEMINI_KEY" ]]; then
    export GEMINI_API_KEY="$GEMINI_KEY"
fi
if [[ -n "$OPENROUTER_KEY" ]]; then
    export OPENROUTER_API_KEY="$OPENROUTER_KEY"
fi

echo "Running models on dataset: $DATASET_NAME"
echo "Task type: $TASK_TYPE"
echo "Tasks from registry:"
for ((i=0; i<${#TASK_ARGS[@]}; i+=2)); do
    if [[ "${TASK_ARGS[i]}" == "--task-id" ]]; then
        echo "  - ${TASK_ARGS[i+1]}"
    fi
done
echo "Number of attempts per model: $N_ATTEMPTS"
echo ""

# Set agent based on task type
if [[ "$TASK_TYPE" == "cli" ]]; then
    CLAUDE_AGENT="terminus-2"
    GPT_AGENT="terminus-2"
else
    CLAUDE_AGENT="claude-code"
    GPT_AGENT="codex"
fi

echo "Using agents: Claude=$CLAUDE_AGENT, GPT=$GPT_AGENT"
echo ""

echo "Running Oracle agent (reference solutions) ($N_ATTEMPTS attempts)..."
uv run tb run \
  --dataset-path "$DATASET_PATH" \
  --agent oracle \
  --log-level warning \
  --n-concurrent 3 \
  --n-attempts 1 \
  --run-id "oracle_$(date +%Y%m%d_%H%M%S)" \
  "${TASK_ARGS[@]}"

# echo ""
# echo "Running Claude Sonnet 4 ($N_ATTEMPTS attempts)..."
# tb run \
#   --dataset-path "$DATASET_PATH" \
#   --agent "$CLAUDE_AGENT" \
#   --model anthropic/claude-sonnet-4-20250514 \
#   --log-level warning \
#   --n-concurrent 2 \
#   --n-attempts "$N_ATTEMPTS" \
#   --run-id "claude4_$(date +%Y%m%d_%H%M%S)" \
#   "${TASK_ARGS[@]}"

# echo ""
# echo "Running GPT-5 ($N_ATTEMPTS attempts)..."
# uv run tb run \
#   --dataset-path "$DATASET_PATH" \
#   --agent "$GPT_AGENT" \
#   --model openai/gpt-5 \
#   --log-level warning \
#   --n-concurrent 2 \
#   --n-attempts "$N_ATTEMPTS" \
#   --run-id "gpt5_$(date +%Y%m%d_%H%M%S)" \
#   "${TASK_ARGS[@]}"

# echo ""
# echo "Running Llama 3.3 via OpenRouter (Groq provider) ($N_ATTEMPTS attempts)..."
# uv run tb run \
#   --dataset-path "$DATASET_PATH" \
#   --agent "$GPT_AGENT" \
#   --model openrouter/meta-llama/llama-3.3-70b-instruct \
#   --agent-kwarg "provider_order=['groq']" \
#   --log-level warning \
#   --n-concurrent 3 \
#   --n-attempts "$N_ATTEMPTS" \
#   --run-id "llama3.3_$(date +%Y%m%d_%H%M%S)" \
#   "${TASK_ARGS[@]}"

echo ""
echo "All runs complete! Check the 'runs/' directory for results."