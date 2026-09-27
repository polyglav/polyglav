FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY plugins ./plugins
COPY polyglav-entrypoint.sh ./polyglav-entrypoint.sh

RUN pip install --no-cache-dir .

ENV POLYGLAV_HOST=0.0.0.0
ENV POLYGLAV_PORT=8787

EXPOSE 8787

ENTRYPOINT ["./polyglav-entrypoint.sh"]
