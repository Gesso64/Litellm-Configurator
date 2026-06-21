#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"

# Use project-local virtual environment if it exists
if [ -d "$DIR/.venv" ]; then
    export PATH="$DIR/.venv/bin:$DIR/.venv/Scripts:$PATH"
    exec "$DIR/.venv/bin/python3" "$DIR/start-litellm-select.py" "$@" 2>/dev/null \
      || exec "$DIR/.venv/Scripts/python" "$DIR/start-litellm-select.py" "$@"
else
    exec python3 "$DIR/start-litellm-select.py" "$@"
fi