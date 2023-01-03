FROM python:3.11-slim

RUN apt update -y
RUN apt install -y build-essential python3-dev libpq-dev

RUN mkdir /opt/project
WORKDIR /opt/project

COPY requirements.txt .
COPY requirements-dev.txt .

RUN pip install -r requirements-dev.txt

COPY entrypoint.sh .
