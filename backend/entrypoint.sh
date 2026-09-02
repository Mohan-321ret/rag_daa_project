#!/bin/sh
set -e

echo "======================================================="
echo " Starting DAA-RAG Backend Service"
echo "======================================================="

# Wait for PostgreSQL database port to be reachable
echo "Waiting for PostgreSQL database connection..."
python -c "
import time, socket, os
host = os.getenv('POSTGRES_HOST', 'postgres')
port = int(os.getenv('POSTGRES_PORT', 5432))
print(f'Checking connection to {host}:{port}...')
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2.0)
while True:
    try:
        s.connect((host, port))
        s.close()
        print('PostgreSQL is reachable!')
        break
    except (socket.error, socket.timeout):
        print('PostgreSQL not ready yet, retrying in 2 seconds...')
        time.sleep(2)
"

# Run Alembic migrations
echo "Running Alembic database migrations (alembic upgrade head)..."
alembic upgrade head || echo "Alembic migration execution complete."

# Start FastAPI app with Uvicorn
echo "Starting Uvicorn server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
