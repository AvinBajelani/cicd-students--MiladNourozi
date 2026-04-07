#!/bin/bash


while true; do
    echo "######################################"
    echo "Running the script..."
    sleep 1
    echo "Current time: $(date +%Y-%m-%d-%H:%M:%S)"
    echo "######################################"
    echo "Checking if the container is running..."
    ls -lh
    echo "working directory: $(pwd)"
    echo "######################################"
done

