# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

param(
    [Parameter()]
    [ValidateSet("gui", "cli", "install", "clean")]
    [string[]]$Tasks = @("gui"),

    [Parameter()]
    [string]$PythonArgs = ""
)

# Project settings
$VenvPath = ".\.venv"
$EnvFile = ".\.env"
$RequirementsFile = ".\requirements.txt"

# Read additional pip flags from environment
$PipFlags = $env:PIP_INSTALL_FLAGS

# Check if virtual environment exists. If not, create it.
# Returns true if venv was created and thus requirements need to be installed
function Enable-Venv {
    if (Test-Path $VenvPath) {
        Write-Host "Activating virtual environment..." -ForegroundColor Cyan
        $InstallingRequirementsNeeded = $false
    } else {
        Write-Host "Virtual environment not found. Creating one..." -ForegroundColor Yellow
        python -m venv $VenvPath
        $InstallingRequirementsNeeded = $true
    }
    & "$VenvPath\Scripts\Activate.ps1"
    return $InstallingRequirementsNeeded
}

# Load environment variables from .env file
function Import-EnvVars {
    if (Test-Path $EnvFile) {
        Write-Host "Loading environment variables from $EnvFile" -ForegroundColor Cyan
        Get-Content $EnvFile | ForEach-Object {
            if ($_ -match "^\s*([^#][^=]+)=(.*)$") {
                $name = $matches[1].Trim()
                $value = $matches[2].Trim()
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
                Write-Host "  Set $name" -ForegroundColor Gray
            }
        }
    } else {
        Write-Host "No .env file found" -ForegroundColor Yellow
    }
}

# Install pip requirements
function Install-Requirements {
    Write-Host "Installing dependencies..." -ForegroundColor Green
    pip install $PipFlags -r $RequirementsFile
}

# Execute a single task
function Invoke-Task {
    param(
        [string]$TaskName
    )

    Write-Host "Executing task: $TaskName" -ForegroundColor Magenta

    switch ($TaskName) {
        "gui" {
            $installNeeded = Enable-Venv
            if ($installNeeded) { Install-Requirements }
            Import-EnvVars
            Write-Host "Opening GUI interface..." -ForegroundColor Green

            Invoke-Expression "python -m src.main_gui"
        }
        "cli" {
            $installNeeded = Enable-Venv
            if ($installNeeded) { Install-Requirements }
            Import-EnvVars
            Write-Host "Running application..." -ForegroundColor Green

            # Construct the command to run the module
            $command = "python -m src.main"
            # Split Python arguments if provided as a string and pass them individually
            if ($PythonArgs) {
                Write-Host "Running with args: $PythonArgs" -ForegroundColor Cyan
                $command += " $PythonArgs"
            }
            Invoke-Expression $command
        }
        "install" {
            $null = Enable-Venv
            Install-Requirements
        }
        "clean" {
            if (Test-Path $VenvPath) {
                Write-Host "Removing virtual environment..." -ForegroundColor Yellow
                Remove-Item -Recurse -Force $VenvPath
            }
            Write-Host "Cleaning cache files..." -ForegroundColor Yellow
            Get-ChildItem -Include "__pycache__", "*.pyc" -Recurse | Remove-Item -Recurse -Force
        }
    }

    Write-Host "Completed task: $TaskName" -ForegroundColor Magenta
}

# Main execution
foreach ($Task in $Tasks) {
    Invoke-Task -TaskName $Task
}
