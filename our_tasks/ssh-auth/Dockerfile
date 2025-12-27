FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    openssh-client sshpass sudo python3 python3-pip tmux asciinema && \
    useradd -m llm && echo "llm:37" | chpasswd && \
    mkdir -p /home/llm/.ssh && \
    chown llm:llm /home/llm/.ssh && \
    chmod 700 /home/llm/.ssh

# Add llm to sudoers
RUN echo "llm ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

CMD ["sleep", "infinity"]
