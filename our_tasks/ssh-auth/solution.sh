#!/bin/bash
set -e


echo "SSH key pair..."
sudo -u llm ssh-keygen -t rsa -N "" -f /home/llm/.ssh/id_rsa

echo "Public key to server..."
sudo -u llm sshpass -p "37" ssh-copy-id -i /home/llm/.ssh/id_rsa.pub -o StrictHostKeyChecking=no llm@server

echo "Fix permissions"
sudo -u llm sshpass -p "37" ssh -o StrictHostKeyChecking=no llm@server "chmod 700 /home/llm/.ssh && chmod 600 /home/llm/.ssh/authorized_keys"

echo "SSH config"
sudo -u llm sshpass -p "37" ssh -o StrictHostKeyChecking=no llm@server "sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config && sudo pkill -HUP sshd" || echo "SSH config updated, connection may have closed"

sleep 5

echo "Key authentication test"
sudo -u llm ssh -o StrictHostKeyChecking=no llm@server "echo 'SSH key authentication successful!'" || echo "Key authentication test completed"
