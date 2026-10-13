FROM python:3.13-slim-bookworm

# Everything the verifier needs is installed here; test.sh installs nothing.
RUN pip install --no-cache-dir pytest==9.1.1 pytest-json-ctrf==0.5.2

COPY . /tests/

# Parent directory of the declared artifact, and the reward directory.
RUN mkdir -p /app/output /logs/verifier

WORKDIR /tests
