FROM ubuntu:24.04

RUN apt update && apt install -y \
    ansible rsync vim \
    && rm -rf /var/lib/apt/lists/*
    
RUN ansible-galaxy collection install ansible.posix

