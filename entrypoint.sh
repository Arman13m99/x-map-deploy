#!/bin/bash
# docker/entrypoint.sh - Main Application Entrypoint

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 TapsiFood Dashboard - Starting Application${NC}"

# Function to wait for service
wait_for_service() {
    local host=$1
    local port=$2
    local service_name=$3
    local max_attempts=${4:-30}
    local attempt=1

    echo -e "${YELLOW}⏳ Waiting for $service_name at $host:$port...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if nc -z "$host" "$port" 2>/dev/null; then
            echo -e "${GREEN}✅ $service_name is ready!${NC}"
            return 0
        fi
        
        echo -e "${YELLOW}   Attempt $attempt/$max_attempts: $service_name not ready yet...${NC}"
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo -e "${RED}❌ $service_name failed to become ready after $max_attempts attempts${NC}"
    return 1
}

# Function to check database connection
check_database() {
    echo -e "${YELLOW}🗄️ Checking database connection...${NC}"
    
    python -c "
import os
import sys
from sqlalchemy import create_engine, text

try:
    engine = create_engine(os.getenv('DATABASE_URL'))
    with engine.connect() as conn:
        result = conn.execute(text('SELECT version()'))
        version = result.fetchone()[0]
        print(f'✅ Database connected: {version[:50]}...')
except Exception as e:
    print(f'❌ Database connection failed: {e}')
    sys.exit(1)
"
}

# Function to check Redis connection
check_redis() {
    echo -e "${YELLOW}🗄️ Checking Redis connection...${NC}"
    
    python -c "
import os
import sys
import redis

try:
    redis_url = os.getenv('REDIS_URL', 'redis://redis:6379')
    client = redis.from_url(redis_url)
    info = client.ping()
    print('✅ Redis connected and responding')
except Exception as e:
    print(f'❌ Redis connection failed: {e}')
    sys.exit(1)
"
}

# Function to run database migrations
run_migrations() {
    echo -e "${YELLOW}🔄 Running database migrations...${NC}"
    
    python -c "
import sys
import os
sys.path.append('/app/backend')

try:
    from models import Base, engine
    Base.metadata.create_all(bind=engine)
    print('✅ Database tables ensured')
except Exception as e:
    print(f'❌ Migration failed: {e}')
    # Don't exit on migration failure for existing deployments
    print('⚠️ Continuing with existing schema...')
"
}

# Function to warm cache on startup
warm_cache_startup() {
    if [ "$ENVIRONMENT" = "production" ] && [ "$WARM_CACHE_ON_STARTUP" = "true" ]; then
        echo -e "${YELLOW}🔥 Warming cache on startup...${NC}"
        
        python -c "
import asyncio
import sys
import os
sys.path.append('/app/backend')

try:
    from cache_manager import CacheManager
    cache = CacheManager()
    
    # Simple cache warming - just check connection
    cache.redis_client.ping()
    print('✅ Cache warming preparation complete')
except Exception as e:
    print(f'⚠️ Cache warming failed: {e}')
" &
    fi
}

# Parse command line arguments
case "$1" in
    web|gunicorn)
        echo -e "${BLUE}🌐 Starting Web Server${NC}"
        
        # Wait for dependencies
        wait_for_service postgres 5432 "PostgreSQL"
        wait_for_service redis 6379 "Redis"
        
        # Check connections
        check_database
        check_redis
        
        # Run migrations
        run_migrations
        
        # Warm cache
        warm_cache_startup
        
        # Set Python path
        export PYTHONPATH="/app/backend:$PYTHONPATH"
        
        # Start gunicorn with provided arguments or defaults
        shift
        if [ $# -eq 0 ]; then
            echo -e "${GREEN}🚀 Starting Gunicorn with default configuration${NC}"
            exec gunicorn \
                --bind 0.0.0.0:8000 \
                --workers ${WORKERS:-4} \
                --worker-class ${WORKER_CLASS:-uvicorn.workers.UvicornWorker} \
                --worker-connections ${WORKER_CONNECTIONS:-1000} \
                --max-requests ${MAX_REQUESTS:-10000} \
                --max-requests-jitter ${MAX_REQUESTS_JITTER:-1000} \
                --timeout ${TIMEOUT:-120} \
                --keep-alive ${KEEPALIVE:-5} \
                --preload \
                --access-logfile /app/logs/access.log \
                --error-logfile /app/logs/error.log \
                --log-level ${LOG_LEVEL:-info} \
                backend.api:app
        else
            echo -e "${GREEN}🚀 Starting Gunicorn with custom arguments${NC}"
            exec gunicorn "$@"
        fi
        ;;
        
    test)
        echo -e "${BLUE}🧪 Running Tests${NC}"
        
        # Wait for test dependencies
        wait_for_service postgres 5432 "PostgreSQL"
        wait_for_service redis 6379 "Redis"
        
        export PYTHONPATH="/app/backend:$PYTHONPATH"
        export ENVIRONMENT="test"
        
        # Run tests
        exec pytest tests/ -v --cov=backend --cov-report=html --cov-report=term
        ;;
        
    migrate)
        echo -e "${BLUE}🗄️ Running Database Migration${NC}"
        
        wait_for_service postgres 5432 "PostgreSQL"
        check_database
        
        export PYTHONPATH="/app/backend:$PYTHONPATH"
        
        python scripts/init_db.py --full-setup
        ;;
        
    health-check)
        echo -e "${BLUE}🏥 Health Check${NC}"
        
        export PYTHONPATH="/app/backend:$PYTHONPATH"
        
        python -c "
import asyncio
import sys
import os
sys.path.append('/app/backend')

try:
    from models import engine
    from cache_manager import CacheManager
    
    # Check database
    with engine.connect() as conn:
        conn.execute('SELECT 1')
    print('✅ Database: Healthy')
    
    # Check cache
    cache = CacheManager()
    cache.redis_client.ping()
    print('✅ Cache: Healthy')
    
    print('✅ Overall: Healthy')
    
except Exception as e:
    print(f'❌ Health check failed: {e}')
    sys.exit(1)
"
        ;;
        
    shell|bash)
        echo -e "${BLUE}🐚 Starting Interactive Shell${NC}"
        export PYTHONPATH="/app/backend:$PYTHONPATH"
        exec /bin/bash
        ;;
        
    *)
        echo -e "${BLUE}🔧 Running Custom Command${NC}"
        export PYTHONPATH="/app/backend:$PYTHONPATH"
        exec "$@"
        ;;
esac