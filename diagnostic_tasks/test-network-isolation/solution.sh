#!/bin/bash

# Test internal network connectivity
if curl -s --max-time 5 http://web-server:8000 > /dev/null; then
    INTERNAL="CONNECTED"
else
    INTERNAL="DISCONNECTED"
fi

# Test internet connectivity
if curl -s --max-time 5 https://www.google.com > /dev/null; then
    INTERNET="CONNECTED"
else
    INTERNET="DISCONNECTED"
fi

# Write results
cat > /app/network_test.json <<EOF
{
  "internal_network": "$INTERNAL",
  "internet": "$INTERNET"
}
EOF

cat /app/network_test.json
