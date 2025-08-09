#!/bin/bash
# docker/worker-entrypoint.sh - Celery Worker Entrypoint

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🔧 TapsiFood Dashboard - Starting Worker${NC}"

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

# Function to check broker connection
check_broker() {
    echo -e "${YELLOW}🔗 Checking Celery broker connection...${NC}"
    
    python -c "
import os
import sys
import redis

try:
    broker_url = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/1')
    if broker_url.startswith('redis://'):
        # Extract connection details
        url_parts = broker_url.replace('redis://', '').split('/')
        host_port = url_parts[0]
        db = url_parts[1] if len(url_parts) > 1 else '0'
        
        if ':' in host_port:
            host, port = host_port.split(':')
            port = int(port)
        else:
            host = host_port
            port = 6379
        
        client = redis.Redis(host=host, port=port, db=int(db))
        client.ping()
        print('✅ Celery broker (Redis) connected')
    else:
        print('⚠️ Non-Redis broker detected, skipping connection test')
        
except Exception as e:
    print(f'❌ Broker connection failed: {e}')
    sys.exit(1)
"
}

# Function to check result backend
check_result_backend() {
    echo -e "${YELLOW}🗃️ Checking Celery result backend...${NC}"
    
    python -c "
import os
import sys
import redis

try:
    result_backend = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/2')
    if result_backend.startswith('redis://'):
        # Extract connection details
        url_parts = result_backend.replace('redis://', '').split('/')
        host_port = url_parts[0]
        db = url_parts[1] if len(url_parts) > 1 else '0'
        
        if ':' in host_port:
            host, port = host_port.split(':')
            port = int(port)
        else:
            host = host_port
            port = 6379
        
        client = redis.Redis(host=host, port=port, db=int(db))
        client.ping()
        print('✅ Celery result backend (Redis) connected')
    else:
        print('⚠️ Non-Redis result backend detected, skipping connection test')
        
except Exception as e:
    print(f'❌ Result backend connection failed: {e}')
    sys.exit(1)
"
}

# Function to validate Celery configuration
validate_celery_config() {
    echo -e "${YELLOW}⚙️ Validating Celery configuration...${NC}"
    
    python -c "
import sys
import os
sys.path.append('/app/backend')

try:
    from celery_config import broker_url, result_backend
    print(f'✅ Broker URL configured: {broker_url[:30]}...')
    print(f'✅ Result backend configured: {result_backend[:30]}...')
    
    # Import tasks to ensure they load properly
    import tasks
    print('✅ Tasks module imported successfully')
    
except Exception as e:
    print(f'❌ Celery configuration validation failed: {e}')
    sys.exit(1)
"
}

# Set Python path
export PYTHONPATH="/app/backend:$PYTHONPATH"

# Parse command line arguments
case "$1" in
    worker)
        echo -e "${BLUE}👷 Starting Celery Worker${NC}"
        
        # Wait for dependencies
        wait_for_service postgres 5432 "PostgreSQL"
        wait_for_service redis 6379 "Redis"
        
        # Check connections
        check_broker
        check_result_backend
        validate_celery_config
        
        # Start worker with provided arguments or defaults
        shift
        if [ $# -eq 0 ]; then
            echo -e "${GREEN}🚀 Starting Celery Worker with default configuration${NC}"
            exec celery -A tasks worker \
                --loglevel=${CELERY_LOG_LEVEL:-info} \
                --concurrency=${CELERY_WORKER_PROCESSES:-4} \
                --max-tasks-per-child=${CELERY_WORKER_MAX_TASKS_PER_CHILD:-1000} \
                --time-limit=${CELERY_TASK_TIME_LIMIT:-7200} \
                --soft-time-limit=${CELERY_TASK_SOFT_TIME_LIMIT:-3600} \
                --queues=default,data_refresh,cache_operations,reports,alerts \
                --prefetch-multiplier=1 \
                --without-gossip \
                --without-mingle \
                --without-heartbeat
        else
            echo -e "${GREEN}🚀 Starting Celery Worker with custom arguments${NC}"
            exec celery -A tasks worker "$@"
        fi
        ;;
        
    beat|scheduler)
        echo -e "${BLUE}⏰ Starting Celery Beat Scheduler${NC}"
        
        # Wait for dependencies
        wait_for_service postgres 5432 "PostgreSQL" 
        wait_for_service redis 6379 "Redis"
        
        # Check connections
        check_broker
        check_result_backend
        validate_celery_config
        
        # Ensure beat schedule directory exists
        mkdir -p /app/celerybeat
        
        shift
        if [ $# -eq 0 ]; then
            echo -e "${GREEN}🚀 Starting Celery Beat with default configuration${NC}"
            exec celery -A tasks beat \
                --loglevel=${CELERY_LOG_LEVEL:-info} \
                --schedule=/app/celerybeat/celerybeat-schedule \
                --pidfile=/app/celerybeat/celerybeat.pid
        else
            echo -e "${GREEN}🚀 Starting Celery Beat with custom arguments${NC}"
            exec celery -A tasks beat "$@"
        fi
        ;;
        
    flower)
        echo -e "${BLUE}🌸 Starting Celery Flower Monitoring${NC}"
        
        # Wait for dependencies
        wait_for_service redis 6379 "Redis"
        
        check_broker
        validate_celery_config
        
        shift
        if [ $# -eq 0 ]; then
            echo -e "${GREEN}🚀 Starting Celery Flower with default configuration${NC}"
            exec celery -A tasks flower \
                --port=${FLOWER_PORT:-5555} \
                --broker=${CELERY_BROKER_URL} \
                --basic_auth=${FLOWER_BASIC_AUTH:-admin:admin}
        else
            echo -e "${GREEN}🚀 Starting Celery Flower with custom arguments${NC}"
            exec celery -A tasks flower "$@"
        fi
        ;;
        
    inspect)
        echo -e "${BLUE}🔍 Celery Inspection${NC}"
        
        check_broker
        validate_celery_config
        
        shift
        if [ $# -eq 0 ]; then
            echo -e "${GREEN}📊 Running Celery inspect stats${NC}"
            exec celery -A tasks inspect stats
        else
            echo -e "${GREEN}📊 Running Celery inspect with custom command${NC}"
            exec celery -A tasks inspect "$@"
        fi
        ;;
        
    purge)
        echo -e "${BLUE}🧹 Purging Celery Tasks${NC}"
        
        check_broker
        validate_celery_config
        
        echo -e "${YELLOW}⚠️ This will delete all pending tasks!${NC}"
        echo -e "${YELLOW}Press Ctrl+C within 10 seconds to cancel...${NC}"
        sleep 10
        
        echo -e "${RED}🗑️ Purging all tasks...${NC}"
        exec celery -A tasks purge -f
        ;;
        
    shell)
        echo -e "${BLUE}🐚 Starting Worker Shell${NC}"
        
        # Optional: wait for dependencies for interactive debugging
        if [ "$WAIT_FOR_DEPS" = "true" ]; then
            wait_for_service postgres 5432 "PostgreSQL"
            wait_for_service redis 6379 "Redis"
        fi
        
        exec /bin/bash
        ;;
        
    test-task)
        echo -e "${BLUE}🧪 Testing Task Execution${NC}"
        
        wait_for_service postgres 5432 "PostgreSQL"
        wait_for_service redis 6379 "Redis"
        check_broker
        check_result_backend
        validate_celery_config
        
        echo -e "${GREEN}🔥 Running test task...${NC}"
        python -c "
import sys
sys.path.append('/app/backend')
from tasks import health_check

try:
    result = health_check.delay()
    print(f'✅ Task queued with ID: {result.task_id}')
    
    # Wait for result with timeout
    import time
    timeout = 30
    start_time = time.time()
    
    while not result.ready() and (time.time() - start_time) < timeout:
        print('⏳ Waiting for task completion...')
        time.sleep(2)
    
    if result.ready():
        print(f'✅ Task completed: {result.result}')
    else:
        print('⚠️ Task did not complete within timeout')
        
except Exception as e:
    print(f'❌ Task execution failed: {e}')
    sys.exit(1)
"
        ;;
        
    *)
        echo -e "${BLUE}🔧 Running Custom Celery Command${NC}"
        
        # For any custom celery command, ensure basic setup
        check_broker
        validate_celery_config
        
        exec celery -A tasks "$@"
        ;;
esac