#!/bin/bash

# parse-cast-file.sh - Parse cast files to extract AI agent messages in readable format
# Usage: ./scripts_bash/parse-cast-file.sh <input.cast> [output.log]

set -euo pipefail

# Function to show usage
show_usage() {
    echo "Usage: $0 <input.cast> [output.log]"
    echo "  input.cast: Path to the cast file to parse"
    echo "  output.log: Path to the output log file (optional)"
    echo "             If not provided, output will be <input.cast.parsed.log>"
}

# Check for help argument
if [ $# -eq 1 ] && ([ "$1" = "-h" ] || [ "$1" = "--help" ] || [ "$1" = "help" ]); then
    show_usage
    exit 0
fi

# Check arguments
if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    show_usage
    exit 1
fi

INPUT_CAST="$1"

# Generate output filename if not provided
if [ $# -eq 1 ]; then
    # Get directory and filename without extension
    INPUT_DIR=$(dirname "$INPUT_CAST")
    INPUT_BASE=$(basename "$INPUT_CAST" .cast)
    OUTPUT_LOG="$INPUT_DIR/$INPUT_BASE.parsed.log"
else
    OUTPUT_LOG="$2"
fi

# Check if input file exists
if [ ! -f "$INPUT_CAST" ]; then
    echo "Error: Input file '$INPUT_CAST' does not exist"
    exit 1
fi

# Create output directory if it doesn't exist
mkdir -p "$(dirname "$OUTPUT_LOG")"

# Initialize output file
echo "# AI Agent Messages from Cast File: $INPUT_CAST" > "$OUTPUT_LOG"
echo "# Generated on: $(date)" >> "$OUTPUT_LOG"
echo "# ========================================" >> "$OUTPUT_LOG"
echo "" >> "$OUTPUT_LOG"

# Extract header information
echo "## Session Information" >> "$OUTPUT_LOG"
head -1 "$INPUT_CAST" | jq -r '
    "Session started: " + (.timestamp | strftime("%Y-%m-%d %H:%M:%S") // (.timestamp | tostring)) +
    "\nTerminal size: " + (.width | tostring) + "x" + (.height | tostring) +
    "\nEnvironment: " + (.env | tostring)
' >> "$OUTPUT_LOG" 2>/dev/null || echo "Session started: $(head -1 "$INPUT_CAST")" >> "$OUTPUT_LOG"

echo "" >> "$OUTPUT_LOG"
echo "## AI Agent Messages" >> "$OUTPUT_LOG"
echo "" >> "$OUTPUT_LOG"

# Create a temporary Python script
cat > /tmp/parse_cast.py << 'EOF'
import json
import sys
import re
from datetime import datetime

def parse_cast_file(input_file, output_file):
    line_count = 0
    json_count = 0
    
    with open(input_file, 'r') as f:
        for line in f:
            line_count += 1
            line = line.strip()
            
            # Extract timestamp from any line that starts with [
            timestamp_match = re.match(r'^\[([0-9.]+)', line)
            timestamp = timestamp_match.group(1) if timestamp_match else '0'
            
            # Check if line contains JSON (starts with [ and contains {)
            if line.startswith('[') and '{' in line and line.endswith(']'):
                json_count += 1
                
                # Extract JSON content - find the JSON part after the second comma
                # Pattern: [timestamp, "o", "json_content"]
                match = re.match(r'^\[([0-9.]+),\s*"o",\s*"(.*)"\]$', line)
                if match:
                    json_content = match.group(2)
                    # Unescape the JSON more carefully
                    json_content = json_content.replace('\\"', '"').replace('\\r', ' ').replace('\\n', '\n').replace('\\\\', '\\')
                    # Also handle escaped backslashes before newlines
                    json_content = json_content.replace('\\\n', '\n')
                    
                    # Try to parse JSON, but if it fails, try to fix common issues
                    data = None
                    try:
                        # Parse JSON
                        data = json.loads(json_content)
                    except json.JSONDecodeError as e:
                        # Try to fix common JSON issues
                        try:
                            # Remove trailing backslashes that might break JSON
                            fixed_json = json_content.rstrip('\\')
                            data = json.loads(fixed_json)
                        except json.JSONDecodeError:
                            # If still fails, try to extract just the essential parts
                            try:
                                # Look for type field even in malformed JSON
                                if '"type":"user"' in json_content:
                                    # This is a user message, try to extract the content
                                    content_match = re.search(r'"content":"([^"]*(?:\\.[^"]*)*)"', json_content)
                                    if content_match:
                                        data = {
                                            'type': 'user',
                                            'message': {
                                                'role': 'user',
                                                'content': [{
                                                    'type': 'tool_result',
                                                    'content': content_match.group(1)
                                                }]
                                            }
                                        }
                                    else:
                                        # Try a simpler approach
                                        if 'tool_result' in json_content:
                                            # Extract the actual content
                                            content_match = re.search(r'"content":"([^"]*(?:\\.[^"]*)*)"', json_content)
                                            actual_content = content_match.group(1) if content_match else json_content
                                            data = {
                                                'type': 'user',
                                                'message': {
                                                    'role': 'user',
                                                    'content': [{
                                                        'type': 'tool_result',
                                                        'content': actual_content
                                                    }]
                                                }
                                            }
                                elif '"type":"assistant"' in json_content:
                                    # This is an assistant message
                                    if 'tool_use' in json_content:
                                        # Try to extract tool name and input
                                        tool_name_match = re.search(r'"name":"([^"]*)"', json_content)
                                        tool_name = tool_name_match.group(1) if tool_name_match else 'Unknown'
                                        # Try to extract the actual input
                                        input_match = re.search(r'"input":\s*(\{[^}]*\})', json_content)
                                        if input_match:
                                            tool_input = input_match.group(1)
                                        else:
                                            # If we can't parse the input, preserve the raw content
                                            tool_input = json_content
                                        data = {
                                            'type': 'assistant',
                                            'message': {
                                                'content': [{
                                                    'type': 'tool_use',
                                                    'name': tool_name,
                                                    'input': tool_input
                                                }]
                                            }
                                        }
                                    else:
                                        # Try to extract text content
                                        text_match = re.search(r'"text":"([^"]*(?:\\.[^"]*)*)"', json_content)
                                        if text_match:
                                            text_content = text_match.group(1)
                                        else:
                                            # If we can't parse the text, preserve the raw content
                                            text_content = json_content
                                        data = {
                                            'type': 'assistant',
                                            'message': {
                                                'content': [{
                                                    'type': 'text',
                                                    'text': text_content
                                                }]
                                            }
                                        }
                                else:
                                    # Unknown type, create a generic structure
                                    data = {
                                        'type': 'unknown',
                                        'raw_content': json_content
                                    }
                            except:
                                # Final fallback
                                data = None
                    
                    if data:
                        # Format based on type
                        if data.get('type') == 'system':
                            formatted = 'SYSTEM INIT: Session=' + str(data.get('session_id', 'unknown')) + ', Model=' + str(data.get('model', 'unknown')) + ', Tools=' + ','.join(data.get('tools', [])) + ', Agents=' + ','.join(data.get('agents', []))
                        elif data.get('type') == 'assistant':
                            message = data.get('message', {})
                            content = message.get('content', [])
                            if content and content[0].get('type') == 'text':
                                formatted = 'ASSISTANT: ' + content[0].get('text', '')
                            elif content and content[0].get('type') == 'tool_use':
                                tool = content[0]
                                formatted = 'ASSISTANT: TOOL[' + tool.get('name', 'unknown') + ']: ' + json.dumps(tool.get('input', {}))
                            else:
                                formatted = 'ASSISTANT: ' + json.dumps(content)
                        elif data.get('type') == 'user':
                            message = data.get('message', {})
                            content = message.get('content', [])
                            if content and content[0].get('type') == 'tool_result':
                                content_text = content[0].get('content', '')
                                formatted = 'USER: TOOL_RESULT: ' + content_text
                            else:
                                formatted = 'USER: ' + json.dumps(content)
                        elif data.get('type') == 'unknown':
                            formatted = 'UNKNOWN: ' + data.get('raw_content', '')
                        else:
                            formatted = str(data.get('type', 'unknown')) + ': ' + json.dumps(data)
                        
                        with open(output_file, 'a') as out:
                            out.write('[' + timestamp + '] ' + formatted + '\n\n')
                            
                    else:
                        # Final fallback: show raw JSON if parsing fails completely
                        with open(output_file, 'a') as out:
                            out.write('[' + timestamp + '] RAW: ' + json_content + '\n\n')
                else:
                    # No JSON content found - still preserve the line
                    with open(output_file, 'a') as out:
                        out.write('[' + timestamp + '] NO_JSON: ' + line + '\n\n')
            else:
                # Line doesn't start with [ or doesn't contain JSON - still preserve it
                if line.startswith('['):
                    # It's a cast line but not JSON
                    with open(output_file, 'a') as out:
                        out.write('[' + timestamp + '] CAST: ' + line + '\n\n')
                else:
                    # It's not a cast line at all - still preserve it
                    with open(output_file, 'a') as out:
                        out.write('[0.000000] OTHER: ' + line + '\n\n')
    
    print('Processing complete!')
    print('Total lines processed: ' + str(line_count))
    print('JSON messages found: ' + str(json_count))
    print('Output written to: ' + output_file)

if __name__ == "__main__":
    parse_cast_file(sys.argv[1], sys.argv[2])
EOF

# Run the Python script
python3 /tmp/parse_cast.py "$INPUT_CAST" "$OUTPUT_LOG"

# Clean up
rm -f /tmp/parse_cast.py