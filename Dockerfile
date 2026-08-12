FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY sortdvr ./sortdvr
RUN pip install --no-cache-dir .

# State lives on a mounted volume so it survives restarts.
ENV DB_PATH=/app/data/sortdvr.db
VOLUME ["/app/data"]

# Dry-run by default (prints intended moves, touches nothing).
# To actually move files, override the command with: sortdvr watch --go
CMD ["sortdvr", "watch"]
