#!/bin/bash
set -e
cd /workspace
python -m pytest tests/test_outputs.py -v -rA --tb=short
