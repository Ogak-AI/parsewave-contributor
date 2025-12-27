#!/bin/bash
pip3 install pytest==8.4.2 paramiko==4.0.0
python3 -m pytest $TEST_DIR/test_outputs.py -v -rA

