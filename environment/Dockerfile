FROM python:3.13-slim-bookworm

# Playwright 1.63.0 pins the Chromium build that recorded the session
# (headless shell 153.0.8010.12). --with-deps runs apt-get update itself.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN pip install --no-cache-dir playwright==1.63.0 \
    && playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/pw-browsers

WORKDIR /app
COPY data/ /app/data/
RUN mkdir -p /app/output
