# Slack Ingester justfile

# Show available commands (default)
default:
    @just --list

# Install dependencies
install:
    uv sync

# Install development dependencies
install-dev:
    uv sync --extra dev

# Install all dependencies (dev + test)
install-all:
    uv sync --extra dev --extra test

# Run tests
test:
    uv run pytest

# Run tests with coverage report
test-coverage:
    uv run pytest --cov=slack_ingester --cov-report=term-missing

# Run tests with HTML coverage report
test-coverage-html:
    uv run pytest --cov=slack_ingester --cov-report=html
    @echo "Coverage report generated in htmlcov/index.html"

# Run linting
lint:
    uv run ruff check .

# Fix linting issues
lint-fix:
    uv run ruff check . --fix

# Format code
format:
    uv run ruff format .

# Type check
typecheck:
    uv run ty check

# Run all checks (lint, typecheck)
check: lint typecheck

# Build the package
build:
    uv build

# Clean build artifacts and cache
clean:
    rm -rf dist/
    rm -rf build/
    rm -rf htmlcov/
    rm -rf .coverage
    rm -rf .pytest_cache/
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete

# Show available commands
help: default
