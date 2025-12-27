#!/bin/bash
set -e
sleep 5

echo "Testing initial password-based connection..."
sshpass -p "devops" ssh -o StrictHostKeyChecking=no devops@server "echo 'Server is ready'"
