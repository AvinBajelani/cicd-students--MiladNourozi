#!/bin/bash

date >> /tmp/script.log
echo "Script executed successfully" >> /tmp/script.log

echo "********************************" >> /tmp/script.log

echo `date +%Y-%m-%d` >> /tmp/script.log
echo "Script executed successfully" >> /tmp/script.log
sleep 5

echo `date +%Y-%m-%d` >> /tmp/script.log
echo "********************** end deployment **********************" >> /tmp/script.log

echo "Script executed successfully" >> /tmp/script.log

echo "############################# end deployment #############################" >> /tmp/script.log