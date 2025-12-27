FROM node:22-bookworm-slim

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code@latest

WORKDIR /root

# Keep container interactive by default; script will invoke `claude`
CMD ["bash"]

