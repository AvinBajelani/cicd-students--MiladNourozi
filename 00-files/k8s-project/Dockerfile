FROM ubuntu:24.04

WORKDIR /app

COPY . .

RUN chmod +x loop_script.sh

ENTRYPOINT ["bash", "loop_script.sh"]

