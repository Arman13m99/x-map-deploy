# tasks.py - Celery Background Tasks
from celery import Celery
from celery.schedules import crontab
from celery.utils.log import get_task_logger
from datetime import datetime, timedelta
import pandas as pd
import geopandas as gpd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import os
import traceback
import asyncio

# Import our modules
from data_pipeline import OptimizedDataPipeline
from cache_manager import CacheManager
from models import engine, DataRefreshLog, Order, Vendor
from mini import fetch_question_data

# Configure Celery
celery_app = Celery('tapsifood_dashboard')
celery_app.config_from_object('celery_config')

logger = get_task_logger(__name__)

# Global instances
pipeline = OptimizedDataPipeline()
cache = CacheManager()

@celery_app.task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 300})
def refresh_all_data(self):
    """Daily complete data refresh task with comprehensive error handling"""
    refresh_log = DataRefreshLog(status='running', started_at=datetime.utcnow())
    
    with Session(engine) as db:
        db.add(refresh_log)
        db.commit()
        refresh_id = refresh_log.refresh_id
    
    try:
        start_time = datetime.utcnow()
        logger.info(f"🚀 Starting data refresh {refresh_id}")
        
        # Update task state
        self.update_state(state='PROGRESS', meta={
            'step': 'Initializing',
            'progress': 0,
            'refresh_id': refresh_id
        })
        
        # Step 1: Fetch fresh data from Metabase
        logger.info("📡 Fetching orders data from Metabase...")
        self.update_state(state='PROGRESS', meta={
            'step': 'Fetching orders data',
            'progress': 10,
            'refresh_id': refresh_id
        })
        
        orders_df = fetch_question_data(
            question_id=pipeline.ORDER_DATA_QUESTION_ID,
            metabase_url=pipeline.METABASE_URL,
            username=pipeline.METABASE_USERNAME,
            password=pipeline.METABASE_PASSWORD,
            workers=8,
            page_size=75000
        )
        
        if orders_df is None or orders_df.empty:
            raise Exception("Failed to fetch orders data or data is empty")
        
        logger.info("📡 Fetching vendors data from Metabase...")
        self.update_state(state='PROGRESS', meta={
            'step': 'Fetching vendors data',
            'progress': 30,
            'refresh_id': refresh_id
        })
        
        vendors_df = fetch_question_data(
            question_id=pipeline.VENDOR_DATA_QUESTION_ID,
            metabase_url=pipeline.METABASE_URL,
            username=pipeline.METABASE_USERNAME,
            password=pipeline.METABASE_PASSWORD,
            workers=8,
            page_size=50000
        )
        
        if vendors_df is None or vendors_df.empty:
            raise Exception("Failed to fetch vendors data or data is empty")
        
        # Step 2: Process and clean data
        logger.info("🔧 Processing and cleaning data...")
        self.update_state(state='PROGRESS', meta={
            'step': 'Processing data',
            'progress': 50,
            'refresh_id': refresh_id
        })
        
        orders_df = pipeline._process_orders_data(orders_df)
        vendors_df = pipeline._process_vendors_data(vendors_df)
        
        # Step 3: Update database with optimized bulk operations
        logger.info("💾 Updating database...")
        self.update_state(state='PROGRESS', meta={
            'step': 'Updating database',
            'progress': 70,
            'refresh_id': refresh_id
        })
        
        await asyncio.run(pipeline._update_database_optimized(orders_df, vendors_df))
        
        # Step 4: Clear and rebuild cache
        logger.info("🗄️ Updating cache...")
        self.update_state(state='PROGRESS', meta={
            'step': 'Updating cache',
            'progress': 85,
            'refresh_id': refresh_id
        })
        
        # Clear old cache
        cache.invalidate_pattern('*')
        
        # Cache base datasets
        await asyncio.run(pipeline._update_cache_parallel(orders_df, vendors_df))
        
        # Step 5: Pre-generate common queries
        logger.info("🔥 Pre-generating common queries...")
        self.update_state(state='PROGRESS', meta={
            'step': 'Pre-generating queries',
            'progress': 95,
            'refresh_id': refresh_id
        })
        
        await asyncio.run(pipeline._pregenerate_common_queries())
        
        # Update refresh log with success
        duration_seconds = int((datetime.utcnow() - start_time).total_seconds())
        with Session(engine) as db:
            log = db.query(DataRefreshLog).filter_by(refresh_id=refresh_id).first()
            log.status = 'completed'
            log.completed_at = datetime.utcnow()
            log.orders_processed = len(orders_df)
            log.vendors_processed = len(vendors_df)
            log.duration_seconds = duration_seconds
            db.commit()
        
        logger.info(f"✅ Data refresh {refresh_id} completed successfully in {duration_seconds}s")
        logger.info(f"📊 Processed {len(orders_df)} orders and {len(vendors_df)} vendors")
        
        # Generate daily report
        generate_daily_report.delay(refresh_id)
        
        return {
            'status': 'success',
            'refresh_id': refresh_id,
            'orders_processed': len(orders_df),
            'vendors_processed': len(vendors_df),
            'duration_seconds': duration_seconds
        }
        
    except Exception as e:
        # Update refresh log with error
        duration_seconds = int((datetime.utcnow() - start_time).total_seconds())
        error_message = str(e)
        error_traceback = traceback.format_exc()
        
        with Session(engine) as db:
            log = db.query(DataRefreshLog).filter_by(refresh_id=refresh_id).first()
            log.status = 'failed'
            log.completed_at = datetime.utcnow()
            log.error_message = f"{error_message}\n\nTraceback:\n{error_traceback}"
            log.duration_seconds = duration_seconds
            db.commit()
        
        logger.error(f"❌ Data refresh {refresh_id} failed: {error_message}")
        logger.error(f"🔍 Full traceback: {error_traceback}")
        
        # Send alert (implement your alerting system here)
        send_alert.delay(
            subject=f"Data Refresh Failed - {refresh_id}",
            message=f"Data refresh failed with error: {error_message}",
            severity="high"
        )
        
        raise

@celery_app.task
def warm_cache():
    """Warm up cache with common queries"""
    try:
        logger.info("🔥 Starting cache warming...")
        
        cities = ['tehran', 'mashhad', 'shiraz']
        business_lines = ['restaurant', 'supermarket', 'coffee_shop', 'pharmacy']
        
        # Generate common combinations
        warmed_queries = 0
        
        # City-only queries
        for city in cities:
            try:
                result = asyncio.run(pipeline.get_filtered_data(city=city))
                if result:
                    warmed_queries += 1
                    logger.info(f"✅ Warmed cache for city: {city}")
            except Exception as e:
                logger.error(f"❌ Failed to warm cache for city {city}: {e}")
        
        # City + Business Line combinations
        for city in cities:
            for bl in business_lines:
                try:
                    result = asyncio.run(pipeline.get_filtered_data(city=city, business_lines=[bl]))
                    if result:
                        warmed_queries += 1
                        logger.info(f"✅ Warmed cache for {city} + {bl}")
                except Exception as e:
                    logger.error(f"❌ Failed to warm cache for {city} + {bl}: {e}")
        
        # Recent date ranges
        end_date = datetime.now()
        for days_back in [7, 30, 90]:
            start_date = end_date - timedelta(days=days_back)
            for city in cities:
                try:
                    result = asyncio.run(pipeline.get_filtered_data(
                        city=city,
                        start_date=start_date.strftime('%Y-%m-%d'),
                        end_date=end_date.strftime('%Y-%m-%d')
                    ))
                    if result:
                        warmed_queries += 1
                        logger.info(f"✅ Warmed cache for {city} last {days_back} days")
                except Exception as e:
                    logger.error(f"❌ Failed to warm cache for {city} last {days_back} days: {e}")
        
        logger.info(f"🎯 Cache warming completed: {warmed_queries} queries warmed")
        return {"status": "success", "queries_warmed": warmed_queries}
        
    except Exception as e:
        logger.error(f"❌ Cache warming failed: {e}")
        return {"status": "error", "error": str(e)}

@celery_app.task
def health_check():
    """System health check task"""
    try:
        health_status = {
            'timestamp': datetime.utcnow().isoformat(),
            'services': {}
        }
        
        # Check database
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            health_status['services']['database'] = 'healthy'
        except Exception as e:
            health_status['services']['database'] = f'unhealthy: {str(e)}'
        
        # Check cache
        try:
            cache.redis_client.ping()
            health_status['services']['cache'] = 'healthy'
        except Exception as e:
            health_status['services']['cache'] = f'unhealthy: {str(e)}'
        
        # Check data freshness
        try:
            with Session(engine) as db:
                last_refresh = db.query(DataRefreshLog).filter_by(status='completed').order_by(DataRefreshLog.started_at.desc()).first()
                if last_refresh:
                    hours_since_refresh = (datetime.utcnow() - last_refresh.started_at).total_seconds() / 3600
                    if hours_since_refresh > 25:  # More than 25 hours (should refresh daily)
                        health_status['services']['data_freshness'] = f'stale: {hours_since_refresh:.1f} hours old'
                    else:
                        health_status['services']['data_freshness'] = f'fresh: {hours_since_refresh:.1f} hours old'
                else:
                    health_status['services']['data_freshness'] = 'unknown: no refresh logs'
        except Exception as e:
            health_status['services']['data_freshness'] = f'error: {str(e)}'
        
        # Overall health
        unhealthy_services = [k for k, v in health_status['services'].items() if not v.startswith('healthy') and not v.startswith('fresh')]
        health_status['overall_status'] = 'healthy' if not unhealthy_services else 'degraded'
        health_status['unhealthy_services'] = unhealthy_services
        
        logger.info(f"🏥 Health check completed: {health_status['overall_status']}")
        
        # Store health status in cache for API endpoint
        cache.cache_json('system_health', health_status, 1)  # Cache for 1 hour
        
        # Send alert if unhealthy
        if unhealthy_services:
            send_alert.delay(
                subject="System Health Alert",
                message=f"Unhealthy services detected: {', '.join(unhealthy_services)}",
                severity="medium"
            )
        
        return health_status
        
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return {"status": "error", "error": str(e)}

@celery_app.task
def generate_daily_report(refresh_id=None):
    """Generate daily performance and usage report"""
    try:
        logger.info("📊 Generating daily report...")
        
        report_date = datetime.utcnow().date()
        
        with Session(engine) as db:
            # Get data counts
            total_orders = db.query(Order).count()
            total_vendors = db.query(Vendor).count()
            
            # Get refresh performance
            if refresh_id:
                last_refresh = db.query(DataRefreshLog).filter_by(refresh_id=refresh_id).first()
            else:
                last_refresh = db.query(DataRefreshLog).filter_by(status='completed').order_by(DataRefreshLog.started_at.desc()).first()
            
            # Get cache statistics
            cache_stats = cache.get_cache_stats()
            
            report = {
                'date': report_date.isoformat(),
                'data_summary': {
                    'total_orders': total_orders,
                    'total_vendors': total_vendors,
                    'last_refresh': {
                        'refresh_id': last_refresh.refresh_id if last_refresh else None,
                        'started_at': last_refresh.started_at.isoformat() if last_refresh else None,
                        'duration_seconds': last_refresh.duration_seconds if last_refresh else None,
                        'orders_processed': last_refresh.orders_processed if last_refresh else None,
                        'vendors_processed': last_refresh.vendors_processed if last_refresh else None
                    } if last_refresh else None
                },
                'cache_performance': cache_stats,
                'system_status': 'operational',
                'generated_at': datetime.utcnow().isoformat()
            }
        
        # Cache the report
        cache.cache_json('daily_report:latest', report, 25)  # Cache for 25 hours
        cache.cache_json(f'daily_report:{report_date.isoformat()}', report, 24 * 7)  # Keep for a week
        
        logger.info(f"📋 Daily report generated for {report_date}")
        return report
        
    except Exception as e:
        logger.error(f"❌ Daily report generation failed: {e}")
        return {"status": "error", "error": str(e)}

@celery_app.task
def send_alert(subject, message, severity="medium"):
    """Send system alerts (implement your preferred alerting method)"""
    try:
        logger.warning(f"🚨 ALERT [{severity.upper()}]: {subject}")
        logger.warning(f"📝 Message: {message}")
        
        # Implement your alerting system here:
        # - Email notifications
        # - Slack webhooks
        # - SMS alerts
        # - PagerDuty integration
        # - etc.
        
        # For now, just log the alert
        alert_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'subject': subject,
            'message': message,
            'severity': severity
        }
        
        # Store in cache for admin dashboard
        alerts_key = 'system_alerts'
        existing_alerts = cache.get_json(alerts_key) or []
        existing_alerts.append(alert_data)
        
        # Keep only last 50 alerts
        if len(existing_alerts) > 50:
            existing_alerts = existing_alerts[-50:]
        
        cache.cache_json(alerts_key, existing_alerts, 24 * 7)  # Keep for a week
        
        return {"status": "sent", "alert": alert_data}
        
    except Exception as e:
        logger.error(f"❌ Alert sending failed: {e}")
        return {"status": "error", "error": str(e)}

@celery_app.task
def cleanup_old_data():
    """Clean up old logs and cache entries"""
    try:
        logger.info("🧹 Starting cleanup of old data...")
        
        # Clean up old refresh logs (keep last 30 days)
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        
        with Session(engine) as db:
            deleted_logs = db.query(DataRefreshLog).filter(DataRefreshLog.started_at < cutoff_date).delete()
            db.commit()
            logger.info(f"🗑️ Deleted {deleted_logs} old refresh logs")
        
        # Clean up old cache entries
        # (Redis handles TTL automatically, but we can clean up specific patterns)
        old_report_keys = cache.redis_client.keys('daily_report:*')
        if old_report_keys:
            # Keep only last 30 daily reports
            old_report_keys.sort()
            if len(old_report_keys) > 30:
                keys_to_delete = old_report_keys[:-30]
                cache.redis_client.delete(*keys_to_delete)
                logger.info(f"🗑️ Deleted {len(keys_to_delete)} old daily reports")
        
        return {"status": "completed", "logs_deleted": deleted_logs}
        
    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        return {"status": "error", "error": str(e)}

# Schedule configuration
celery_app.conf.beat_schedule = {
    'daily-data-refresh': {
        'task': 'tasks.refresh_all_data',
        'schedule': crontab(hour=9, minute=0),  # 9:00 AM daily
    },
    'hourly-cache-warm': {
        'task': 'tasks.warm_cache',
        'schedule': crontab(minute=0),  # Every hour
    },
    'system-health-check': {
        'task': 'tasks.health_check',
        'schedule': crontab(minute='*/15'),  # Every 15 minutes
    },
    'weekly-cleanup': {
        'task': 'tasks.cleanup_old_data',
        'schedule': crontab(hour=2, minute=0, day_of_week=1),  # Monday 2:00 AM
    },
}