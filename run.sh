#!/bin/bash
# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

# Default task is "gui" if no tasks are provided.
TASKS=()
PYTHON_ARGS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -Tasks)
            shift
            while [[ $# -gt 0 ]] && ! [[ "$1" =~ ^- ]]; do
                TASKS+=("$1")
                shift
            done
            ;;
        -PythonArgs)
            PYTHON_ARGS="$2"
            shift 2
            ;;
        *)
            # Capture tasks that are not passed with -Tasks flag
            if ! [[ "$1" =~ ^- ]]; then
                TASKS+=("$1")
            fi
            shift
            ;;
    esac
done

# If no tasks were provided, default to "gui"
if [ ${#TASKS[@]} -eq 0 ]; then
    TASKS=("gui")
fi

# Project settings
VENV_PATH="./.venv"
ENV_FILE="./.env"
REQUIREMENTS_FILE="./requirements.txt"

# Read additional pip flags from environment
# This is the same: $PIP_INSTALL_FLAGS is used by pip command

# Check if virtual environment exists. If not, create it.
# Returns 0 if venv was created and thus requirements need to be installed
function enable_venv {
    if [ -d "$VENV_PATH" ]; then
        echo "Activating virtual environment..."
        # shellcheck disable=SC1091
        source "$VENV_PATH/bin/activate"
        return 1 # false, no install needed
    else
        echo "Virtual environment not found. Creating one..."
        python3 -m venv "$VENV_PATH"
        # shellcheck disable=SC1091
        source "$VENV_PATH/bin/activate"
        return 0 # true, install needed
    fi
}

# Load environment variables from .env file
function import_env_vars {
    if [ -f "$ENV_FILE" ]; then
        echo "Loading environment variables from $ENV_FILE"
        set -o allexport
        # shellcheck disable=SC1090
        source "$ENV_FILE"
        set +o allexport
    else
        echo "No .env file found"
    fi
}

# Install pip requirements
function install_requirements {
    echo "Installing dependencies..."
    # We can pass flags via the environment variable
    # shellcheck disable=SC2086
    pip install $PIP_INSTALL_FLAGS -r "$REQUIREMENTS_FILE"
}

# Execute a single task
function invoke_task {
    local TaskName=$1
    echo "Executing task: $TaskName"

    case $TaskName in
        "gui")
            enable_venv
            local install_needed=$?
            if [ $install_needed -eq 0 ]; then
                install_requirements
            fi
            import_env_vars
            echo "Opening GUI interface..."
            python3 -m src.main_gui
            ;;
        "cli")
            enable_venv
            local install_needed=$?
            if [ $install_needed -eq 0 ]; then
                install_requirements
            fi
            import_env_vars
            echo "Running application..."
            if [ -n "$PYTHON_ARGS" ]; then
                echo "Running with args: $PYTHON_ARGS"
                # shellcheck disable=SC2086
                python3 -m src.main $PYTHON_ARGS
            else
                python3 -m src.main
            fi
            ;;
        "install")
            enable_venv
            install_requirements
            ;;
        "clean")
            if [ -d "$VENV_PATH" ]; then
                echo "Removing virtual environment..."
                rm -rf "$VENV_PATH"
            fi
            echo "Cleaning cache files..."
            find . -type d -name "__pycache__" -exec rm -rf {} +
            find . -type f -name "*.pyc" -delete
            ;;
        *)
            echo "Unknown task: $TaskName"
            ;;
    esac

    echo "Completed task: $TaskName"
}

# Main execution
for task in "${TASKS[@]}"; do
    invoke_task "$task"
done
