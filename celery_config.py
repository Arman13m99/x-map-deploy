# celery_config.py - Production Celery Configuration
import os
from kombu import Queue

# Redis Configuration
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
broker_url = f'{redis_url}/1'
result_backend = f'{redis_url}/2'

# Serialization
task_serializer = 'pickle'
accept_content = ['pickle', 'json']
result_serializer = 'pickle'
result_accept_content = ['pickle', 'json']

# Timezone
timezone = 'Asia/Tehran'
enable_utc = True

# Task routing and queues
task_default_queue = 'default'
task_queues = (
    Queue('default', routing_key='default'),
    Queue('data_refresh', routing_key='data_refresh'),
    Queue('cache_operations', routing_key='cache_operations'),
    Queue('reports', routing_key='reports'),
    Queue('alerts', routing_key='alerts'),
)

task_routes = {
    'tasks.refresh_all_data': {'queue': 'data_refresh'},
    'tasks.warm_cache': {'queue': 'cache_operations'},
    'tasks.health_check': {'queue': 'default'},
    'tasks.generate_daily_report': {'queue': 'reports'},
    'tasks.send_alert': {'queue': 'alerts'},
    'tasks.cleanup_old_data': {'queue': 'default'},
}

# Worker Configuration
worker_pool = 'prefork'
worker_processes = 4
worker_max_tasks_per_child = 1000
worker_disable_rate_limits = False

# Task execution
task_soft_time_limit = 3600  # 1 hour soft limit
task_time_limit = 7200       # 2 hour hard limit
task_acks_late = True
worker_prefetch_multiplier = 1

# Result backend settings
result_expires = 3600  # Results expire after 1 hour
result_compression = 'gzip'

# Monitoring
worker_send_task_events = True
task_send_sent_event = True

# Error handling
task_reject_on_worker_lost = True
task_ignore_result = False

# Security
worker_hijack_root_logger = False
worker_log_color = False

# Redis connection pool settings
broker_connection_retry_on_startup = True
broker_connection_retry = True
broker_connection_max_retries = 10

# Advanced settings for production
worker_pool_restarts = True
task_track_started = True
task_publish_retry = True
task_publish_retry_policy = {
    'max_retries': 3,
    'interval_start': 0,
    'interval_step': 0.2,
    'interval_max': 0.2,
}

# Beat schedule persistence
beat_schedule_filename = '/tmp/celerybeat-schedule'
beat_sync_every = 1

# Logging
worker_log_format = '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s'
worker_task_log_format = '[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s'