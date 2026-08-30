FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 YT_VISUALS_ROOT=/app YT_CHANNELOPS_SERVER_MODE=1 YT_CHANNELOPS_CONFIG_ROOT=/config YT_CHANNELOPS_PROJECTS_ROOT=/projects YT_CHANNELOPS_LIBRARY_ROOT=/library YT_CHANNELOPS_RELEASES_ROOT=/releases YT_CHANNELOPS_TEMP_ROOT=/temp
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg sqlite3 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint
RUN chmod +x /usr/local/bin/docker-entrypoint
EXPOSE 8765
ENTRYPOINT ["docker-entrypoint"]
CMD ["gunicorn", "--bind", "0.0.0.0:8765", "--workers", "2", "--timeout", "120", "yt_visuals.producer.wsgi:app"]
