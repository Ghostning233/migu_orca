#!/bin/bash
# Ralph Wiggum - Long-running AI agent loop
# Usage: ./ralph.sh [--tool amp|claude|codex|dsh] [--provider PROVIDER] [--model MODEL] [max_iterations]
#
# --tool dsh    Run through the DeepSeek Harness headless profile
#               (dsh --profile headless). The default model comes from
#               $DSH_HOME/settings.yaml's agent-default-model section
#               (e.g. commandcode / deepseek/deepseek-v4-flash).
# --provider    DSH LLM provider for --tool dsh. Examples:
#                 commandcode      - Command Code API (needs @mars-sea/dsh-commandcode-provider
#                                    installed in the headless profile; model ids carry a
#                                    deepseek/ prefix, e.g. deepseek/deepseek-v4-flash)
#                 deepseek-official- DeepSeek official API (model ids are bare, e.g.
#                                    deepseek-v4-flash)
#               When omitted, the provider from $DSH_HOME/settings.yaml is used.
# --model       The model identifier passed straight through to the settings
#               agent-default-model.model field, verbatim. Keep the provider's
#               own prefix convention (commandcode wants deepseek/deepseek-v4-flash).
# --claude-model Alias for --model kept for backwards compatibility (codex/claude only).

set -e

# Parse arguments
TOOL="codex" # Default to the available local Codex CLI for this project.
MAX_ITERATIONS=10
MODEL="${RALPH_MODEL:-}"
PROVIDER="${RALPH_PROVIDER:-}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --tool)
      TOOL="$2"
      shift 2
      ;;
    --tool=*)
      TOOL="${1#*=}"
      shift
      ;;
    --provider)
      PROVIDER="$2"
      shift 2
      ;;
    --provider=*)
      PROVIDER="${1#*=}"
      shift
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --model=*)
      MODEL="${1#*=}"
      shift
      ;;
    --claude-model)
      MODEL="$2"
      shift 2
      ;;
    --claude-model=*)
      MODEL="${1#*=}"
      shift
      ;;
    *)
      # Assume it's max_iterations if it's a number
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        MAX_ITERATIONS="$1"
      fi
      shift
      ;;
  esac
done

# Validate tool choice
if [[ "$TOOL" != "amp" && "$TOOL" != "claude" && "$TOOL" != "codex" && "$TOOL" != "dsh" ]]; then
  echo "Error: Invalid tool '$TOOL'. Must be 'amp', 'claude', 'codex', or 'dsh'."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_FILE="$SCRIPT_DIR/prd.json"
PROGRESS_FILE="$SCRIPT_DIR/progress.txt"
ARCHIVE_DIR="$SCRIPT_DIR/archive"
LAST_BRANCH_FILE="$SCRIPT_DIR/.last-branch"

# Archive previous run if branch changed
if [ -f "$PRD_FILE" ] && [ -f "$LAST_BRANCH_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  LAST_BRANCH=$(cat "$LAST_BRANCH_FILE" 2>/dev/null || echo "")

  if [ -n "$CURRENT_BRANCH" ] && [ -n "$LAST_BRANCH" ] && [ "$CURRENT_BRANCH" != "$LAST_BRANCH" ]; then
    # Archive the previous run
    DATE=$(date +%Y-%m-%d)
    # Strip "ralph/" prefix from branch name for folder
    FOLDER_NAME=$(echo "$LAST_BRANCH" | sed 's|^ralph/||')
    ARCHIVE_FOLDER="$ARCHIVE_DIR/$DATE-$FOLDER_NAME"

    echo "Archiving previous run: $LAST_BRANCH"
    mkdir -p "$ARCHIVE_FOLDER"
    [ -f "$PRD_FILE" ] && cp "$PRD_FILE" "$ARCHIVE_FOLDER/"
    [ -f "$PROGRESS_FILE" ] && cp "$PROGRESS_FILE" "$ARCHIVE_FOLDER/"
    echo "   Archived to: $ARCHIVE_FOLDER"

    # Reset progress file for new run
    echo "# Ralph Progress Log" > "$PROGRESS_FILE"
    echo "Started: $(date)" >> "$PROGRESS_FILE"
    echo "---" >> "$PROGRESS_FILE"
  fi
fi

# Track current branch
if [ -f "$PRD_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  if [ -n "$CURRENT_BRANCH" ]; then
    echo "$CURRENT_BRANCH" > "$LAST_BRANCH_FILE"
  fi
fi

# Initialize progress file if it doesn't exist
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Ralph Progress Log" > "$PROGRESS_FILE"
  echo "Started: $(date)" >> "$PROGRESS_FILE"
  echo "---" >> "$PROGRESS_FILE"
fi

MODEL_LABEL="${MODEL:-default}"
PROVIDER_LABEL="${PROVIDER:-default}"
echo "Starting Ralph - Tool: $TOOL - Model: $MODEL_LABEL - Provider: $PROVIDER_LABEL - Max iterations: $MAX_ITERATIONS"

# --- dsh-specific setup ---------------------------------------------------
# The headless profile (dsh --profile headless) ships with only the base and
# headless bundles; the Command Code provider used by this project
# (@mars-sea/dsh-commandcode-provider) is NOT included by default. Install it
# into the headless profile on demand (idempotent, safe to re-run) so
# --provider commandcode works out of the box on any machine.
#
# When --provider/--model are given for --tool dsh, point the settings-file
# plugin at a temporary document carrying the agent-default-model override so
# the global $DSH_HOME/settings.yaml is never touched. The patch + document
# live under a mktemp dir and are removed when the loop exits.
DSH_PATCH_FILE=""
DSH_SETTINGS_FILE=""
DSH_TMP_DIR=""

cleanup_dsh_tmp() {
  if [[ -n "$DSH_TMP_DIR" && -d "$DSH_TMP_DIR" ]]; then
    rm -rf "$DSH_TMP_DIR"
  fi
}
trap cleanup_dsh_tmp EXIT

if [[ "$TOOL" == "dsh" ]]; then
  if ! command -v dsh >/dev/null 2>&1; then
    echo "Error: --tool dsh requires the 'dsh' CLI (DeepSeek Harness) on PATH." >&2
    exit 1
  fi
  # Idempotently make the Command Code provider available to the headless profile.
  if [[ -n "$PROVIDER" && "$PROVIDER" == "commandcode" ]] || [[ -z "$PROVIDER" ]]; then
    if ! grep -q "dsh-commandcode-provider" "$DSH_HOME/profiles/headless/package.json" 2>/dev/null; then
      echo "dsh: installing @mars-sea/dsh-commandcode-provider into the headless profile..."
      dsh plugin --profile headless add @mars-sea/dsh-commandcode-provider >/dev/null 2>&1 || true
    fi
  fi
fi

if [[ "$TOOL" == "dsh" && ( -n "$PROVIDER" || -n "$MODEL" ) ]]; then
  # --provider alone is meaningless; --model alone keeps the settings.yaml
  # default provider (the temporary document only overrides the model field).
  if [[ -z "$MODEL" && -n "$PROVIDER" ]]; then
    echo "Error: --tool dsh with --provider needs --model." >&2
    exit 1
  fi
  DSH_TMP_DIR="$(mktemp -d)"
  DSH_SETTINGS_FILE="$DSH_TMP_DIR/settings.yml"
  DSH_PATCH_FILE="$DSH_TMP_DIR/patch.yml"
  if [[ -n "$PROVIDER" ]]; then
    cat > "$DSH_SETTINGS_FILE" <<EOF
agent-default-model:
  provider: $PROVIDER
  model: $MODEL
EOF
    echo "dsh: overriding agent-default-model via temporary settings ($PROVIDER / $MODEL)"
  else
    # Only the model is overridden; the provider stays whatever the global
    # settings.yaml resolves to (settings merge keeps the base provider when
    # this section omits it? No - agent-default-model requires both fields, so
    # read the current provider from the global settings and carry it over).
    GLOBAL_PROVIDER=$(grep -A2 '^agent-default-model:' "$DSH_HOME/settings.yaml" 2>/dev/null | grep 'provider:' | head -1 | sed 's/.*provider:[[:space:]]*//')
    if [[ -z "$GLOBAL_PROVIDER" ]]; then
      GLOBAL_PROVIDER="commandcode"
    fi
    cat > "$DSH_SETTINGS_FILE" <<EOF
agent-default-model:
  provider: $GLOBAL_PROVIDER
  model: $MODEL
EOF
    echo "dsh: overriding agent-default-model model only ($GLOBAL_PROVIDER / $MODEL)"
  fi
  cat > "$DSH_PATCH_FILE" <<EOF
- id: settings
  config:
    path: $DSH_SETTINGS_FILE
EOF
fi

for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "==============================================================="
  echo "  Ralph Iteration $i of $MAX_ITERATIONS ($TOOL)"
  echo "==============================================================="

  # Run the selected tool with the ralph prompt
  if [[ "$TOOL" == "amp" ]]; then
    OUTPUT=$(cat "$SCRIPT_DIR/prompt.md" | amp --dangerously-allow-all 2>&1 | tee /dev/stderr) || true
    COMPLETION_OUTPUT="$OUTPUT"
  elif [[ "$TOOL" == "codex" ]]; then
    LAST_MESSAGE_FILE=$(mktemp)
    CODEX_ARGS=(exec --dangerously-bypass-approvals-and-sandbox --output-last-message "$LAST_MESSAGE_FILE")
    if [[ -n "$MODEL" ]]; then
      CODEX_ARGS+=(--model "$MODEL")
    fi
    CODEX_ARGS+=(-)
    OUTPUT=$(codex "${CODEX_ARGS[@]}" < "$SCRIPT_DIR/CODEX.md" 2>&1 | tee /dev/stderr) || true
    COMPLETION_OUTPUT=$(cat "$LAST_MESSAGE_FILE" 2>/dev/null || true)
    rm -f "$LAST_MESSAGE_FILE"
  elif [[ "$TOOL" == "dsh" ]]; then
    DSH_ARGS=(--profile headless)
    if [[ -n "$DSH_PATCH_FILE" ]]; then
      DSH_ARGS+=(--patch "$DSH_PATCH_FILE")
    fi
    # The task text is the ralph prompt; dsh headless prints the final
    # assistant message to stdout, which carries the <promise>COMPLETE</promise>
    # marker when every story is done.
    OUTPUT=$(dsh "${DSH_ARGS[@]}" "$(cat "$SCRIPT_DIR/prompt.md")" 2>&1 | tee /dev/stderr) || true
    COMPLETION_OUTPUT="$OUTPUT"
  else
    # Claude Code: use --dangerously-skip-permissions for autonomous operation, --print for output
    CLAUDE_ARGS=(--dangerously-skip-permissions --print)
    if [[ -n "$MODEL" ]]; then
      CLAUDE_ARGS+=(--model "$MODEL")
    fi
    OUTPUT=$(claude "${CLAUDE_ARGS[@]}" < "$SCRIPT_DIR/CLAUDE.md" 2>&1 | tee /dev/stderr) || true
    COMPLETION_OUTPUT="$OUTPUT"
  fi

  # Check for completion signal
  if echo "$COMPLETION_OUTPUT" | grep -q "<promise>COMPLETE</promise>"; then
    echo ""
    echo "Ralph completed all tasks!"
    echo "Completed at iteration $i of $MAX_ITERATIONS"
    exit 0
  fi

  echo "Iteration $i complete. Continuing..."
  sleep 2
done

echo ""
echo "Ralph reached max iterations ($MAX_ITERATIONS) without completing all tasks."
echo "Check $PROGRESS_FILE for status."
exit 1
