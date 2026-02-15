#!/bin/sh

for i in $(seq 1 10); do
    echo "Test $i"
    mkdir -p "test$i"
    ls -l
    sleep 1
done