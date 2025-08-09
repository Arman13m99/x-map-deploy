# scripts/health_check.py - System Monitoring and Health Checks
import os
import sys
import json
import time
import requests
import psutil
from datetime import datetime, timedelta
import argparse
import logging
from typing import Dict, List, Any

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

try:
    from models import engine
    from cache_manager import CacheManager
    from sqlalchemy import text
except ImportError as e:
    print(f"Warning: Could not import backend modules: {e}")
    engine = None
    CacheManager = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HealthChecker:
    """Comprehensive system health monitoring"""
    
    def __init__(self, api_url="http://localhost"):
        self.api_url = api_url.rstrip('/')
        self.cache = CacheManager() if CacheManager else None
        
    def check_all(self) -> Dict[str, Any]:
        """Run all health checks"""
        logger.info("🏥 Starting comprehensive health check...")
        
        results = {
            'timestamp': datetime.utcnow().isoformat(),
            'overall_status': 'unknown',
            'checks': {}
        }
        
        # Individual health checks
        checks = [
            ('api', self.check_api),
            ('database', self.check_database),
            ('cache', self.check_cache),
            ('celery', self.check_celery),
            ('system_resources', self.check_system_resources),
            ('data_freshness', self.check_data_freshness),
            ('response_times', self.check_response_times)
        ]
        
        healthy_checks = 0
        total_checks = len(checks)
        
        for check_name, check_func in checks:
            try:
                result = check_func()
                results['checks'][check_name] = result
                if result.get('status') == 'healthy':
                    healthy_checks += 1
                logger.info(f"✅ {check_name}: {result.get('status', 'unknown')}")
            except Exception as e:
                results['checks'][check_name] = {
                    'status': 'error',
                    'message': str(e),
                    'timestamp': datetime.utcnow().isoformat()
                }
                logger.error(f"❌ {check_name}: {str(e)}")
        
        # Determine overall status
        if healthy_checks == total_checks:
            results['overall_status'] = 'healthy'
        elif healthy_checks > total_checks * 0.7:
            results['overall_status'] = 'degraded'
        else:
            results['overall_status'] = 'unhealthy'
        
        results['health_score'] = (healthy_checks / total_checks) * 100
        
        logger.info(f"🎯 Overall health: {results['overall_status']} ({results['health_score']:.1f}%)")
        
        return results
    
    def check_api(self) -> Dict[str, Any]:
        """Check API endpoint health"""
        try:
            response = requests.get(f"{self.api_url}/api/v2/health", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'status': 'healthy',
                    'response_time': response.elapsed.total_seconds(),
                    'api_version': data.get('version', 'unknown'),
                    'timestamp': datetime.utcnow().isoformat()
                }
            else:
                return {
                    'status': 'unhealthy',
                    'message': f"HTTP {response.status_code}",
                    'response_time': response.elapsed.total_seconds(),
                    'timestamp': datetime.utcnow().isoformat()
                }
                
        except requests.exceptions.RequestException as e:
            return {
                'status': 'error',
                'message': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def check_database(self) -> Dict[str, Any]:
        """Check database connectivity and performance"""
        if not engine:
            return {
                'status': 'error',
                'message': 'Database engine not available',
                'timestamp': datetime.utcnow().isoformat()
            }
        
        try:
            start_time = time.time()
            
            with engine.connect() as conn:
                # Basic connectivity test
                result = conn.execute(text("SELECT 1")).fetchone()
                
                # Check database version
                version_result = conn.execute(text("SELECT version()")).fetchone()
                db_version = version_result[0] if version_result else "unknown"
                
                # Check database size
                size_result = conn.execute(text("""
                    SELECT pg_size_pretty(pg_database_size(current_database()))
                """)).fetchone()
                db_size = size_result[0] if size_result else "unknown"
                
                # Check active connections
                connections_result = conn.execute(text("""
                    SELECT count(*) FROM pg_stat_activity 
                    WHERE state = 'active'
                """)).fetchone()
                active_connections = connections_result[0] if connections_result else 0
                
                response_time = time.time() - start_time
                
                return {
                    'status': 'healthy',
                    'response_time': response_time,
                    'version': db_version[:50] + "..." if len(db_version) > 50 else db_version,
                    'size': db_size,
                    'active_connections': active_connections,
                    'timestamp': datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def check_cache(self) -> Dict[str, Any]:
        """Check Redis cache health"""
        if not self.cache:
            return {
                'status': 'error',
                'message': 'Cache manager not available',
                'timestamp': datetime.utcnow().isoformat()
            }
        
        try:
            start_time = time.time()
            
            # Test ping
            self.cache.redis_client.ping()
            
            # Get cache info
            info = self.cache.redis_client.info()
            
            response_time = time.time() - start_time
            
            return {
                'status': 'healthy',
                'response_time': response_time,
                'memory_usage': info.get('used_memory_human', 'unknown'),
                'connected_clients': info.get('connected_clients', 0),
                'key_count': self.cache.redis_client.dbsize(),
                'hit_rate': self.cache._calculate_hit_rate(),
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def check_celery(self) -> Dict[str, Any]:
        """Check Celery worker and scheduler health"""
        try:
            # Try to call Celery inspect
            import subprocess
            
            # Check if workers are running
            result = subprocess.run(
                ['celery', '-A', 'tasks', 'inspect', 'ping'],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=os.path.join(os.path.dirname(__file__), '..', 'backend')
            )
            
            if result.returncode == 0:
                # Parse worker response
                output = result.stdout
                
                # Check for active workers
                if 'pong' in output.lower():
                    return {
                        'status': 'healthy',
                        'message': 'Workers responding',
                        'output': output.strip(),
                        'timestamp': datetime.utcnow().isoformat()
                    }
                else:
                    return {
                        'status': 'degraded',
                        'message': 'Workers not responding properly',
                        'output': output.strip(),
                        'timestamp': datetime.utcnow().isoformat()
                    }
            else:
                return {
                    'status': 'unhealthy',
                    'message': 'Celery inspect failed',
                    'error': result.stderr.strip(),
                    'timestamp': datetime.utcnow().isoformat()
                }
                
        except subprocess.TimeoutExpired:
            return {
                'status': 'unhealthy',
                'message': 'Celery inspect timeout',
                'timestamp': datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def check_system_resources(self) -> Dict[str, Any]:
        """Check system resource usage"""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory usage
            memory = psutil.virtual_memory()
            
            # Disk usage
            disk = psutil.disk_usage('/')
            
            # Load average (Unix only)
            load_avg = None
            try:
                load_avg = os.getloadavg()
            except (OSError, AttributeError):
                pass  # Windows doesn't have load average
            
            # Determine health status
            status = 'healthy'
            warnings = []
            
            if cpu_percent > 80:
                status = 'degraded'
                warnings.append(f"High CPU usage: {cpu_percent}%")
            
            if memory.percent > 85:
                status = 'degraded'
                warnings.append(f"High memory usage: {memory.percent}%")
            
            if disk.percent > 90:
                status = 'degraded'
                warnings.append(f"High disk usage: {disk.percent}%")
            
            return {
                'status': status,
                'warnings': warnings,
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_available': memory.available,
                'disk_percent': disk.percent,
                'disk_free': disk.free,
                'load_average': load_avg,
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def check_data_freshness(self) -> Dict[str, Any]:
        """Check if data is up to date"""
        if not engine:
            return {
                'status': 'error',
                'message': 'Database not available',
                'timestamp': datetime.utcnow().isoformat()
            }
        
        try:
            with engine.connect() as conn:
                # Check latest data refresh log
                result = conn.execute(text("""
                    SELECT started_at, completed_at, status, duration_seconds
                    FROM data_refresh_logs 
                    ORDER BY started_at DESC 
                    LIMIT 1
                """)).fetchone()
                
                if not result:
                    return {
                        'status': 'warning',
                        'message': 'No data refresh logs found',
                        'timestamp': datetime.utcnow().isoformat()
                    }
                
                last_refresh = result.started_at
                status = result.status
                duration = result.duration_seconds
                
                # Calculate hours since last refresh
                hours_since = (datetime.utcnow() - last_refresh).total_seconds() / 3600
                
                # Determine status
                if status == 'failed':
                    check_status = 'unhealthy'
                    message = f"Last refresh failed {hours_since:.1f} hours ago"
                elif hours_since > 26:  # More than 26 hours (should refresh daily)
                    check_status = 'degraded'
                    message = f"Data is stale ({hours_since:.1f} hours old)"
                elif hours_since > 25:
                    check_status = 'warning'
                    message = f"Data refresh overdue ({hours_since:.1f} hours old)"
                else:
                    check_status = 'healthy'
                    message = f"Data is fresh ({hours_since:.1f} hours old)"
                
                return {
                    'status': check_status,
                    'message': message,
                    'last_refresh': last_refresh.isoformat(),
                    'hours_since_refresh': hours_since,
                    'last_status': status,
                    'last_duration': duration,
                    'timestamp': datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def check_response_times(self) -> Dict[str, Any]:
        """Check API response times for key endpoints"""
        endpoints = [
            '/api/v2/health',
            '/api/v2/initial-data',
            '/api/v2/map-data?city=tehran'
        ]
        
        results = {}
        slow_endpoints = []
        failed_endpoints = []
        
        for endpoint in endpoints:
            try:
                start_time = time.time()
                response = requests.get(f"{self.api_url}{endpoint}", timeout=30)
                response_time = time.time() - start_time
                
                results[endpoint] = {
                    'response_time': response_time,
                    'status_code': response.status_code,
                    'success': response.status_code == 200
                }
                
                if response.status_code != 200:
                    failed_endpoints.append(endpoint)
                elif response_time > 5.0:  # Slow if > 5 seconds
                    slow_endpoints.append(endpoint)
                    
            except Exception as e:
                results[endpoint] = {
                    'error': str(e),
                    'success': False
                }
                failed_endpoints.append(endpoint)
        
        # Determine overall status
        if failed_endpoints:
            status = 'unhealthy'
            message = f"Failed endpoints: {failed_endpoints}"
        elif slow_endpoints:
            status = 'degraded'
            message = f"Slow endpoints: {slow_endpoints}"
        else:
            status = 'healthy'
            message = "All endpoints responding normally"
        
        return {
            'status': status,
            'message': message,
            'endpoints': results,
            'timestamp': datetime.utcnow().isoformat()
        }
    
    def save_report(self, results: Dict[str, Any], output_file: str = None):
        """Save health check results to file"""
        if not output_file:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"health_report_{timestamp}.json"
        
        try:
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"Health report saved to {output_file}")
        except Exception as e:
            logger.error(f"Failed to save report: {e}")
    
    def send_alert(self, results: Dict[str, Any]):
        """Send alert if system is unhealthy"""
        if results['overall_status'] in ['unhealthy', 'degraded']:
            logger.warning(f"🚨 ALERT: System status is {results['overall_status']}")
            
            # Here you can implement your alerting logic:
            # - Send email
            # - Post to Slack
            # - Create PagerDuty incident
            # - etc.
            
            # Example Slack webhook (uncomment and configure)
            # self._send_slack_alert(results)
    
    def _send_slack_alert(self, results: Dict[str, Any]):
        """Send Slack alert (example implementation)"""
        webhook_url = os.getenv('SLACK_WEBHOOK_URL')
        if not webhook_url:
            return
        
        try:
            failed_checks = [
                name for name, result in results['checks'].items()
                if result.get('status') not in ['healthy', 'warning']
            ]
            
            message = {
                "text": f"🚨 TapsiFood Dashboard Health Alert",
                "attachments": [
                    {
                        "color": "danger" if results['overall_status'] == 'unhealthy' else "warning",
                        "fields": [
                            {
                                "title": "Overall Status",
                                "value": results['overall_status'].upper(),
                                "short": True
                            },
                            {
                                "title": "Health Score",
                                "value": f"{results['health_score']:.1f}%",
                                "short": True
                            },
                            {
                                "title": "Failed Checks",
                                "value": ", ".join(failed_checks) if failed_checks else "None",
                                "short": False
                            }
                        ],
                        "ts": int(time.time())
                    }
                ]
            }
            
            response = requests.post(webhook_url, json=message, timeout=10)
            if response.status_code == 200:
                logger.info("Slack alert sent successfully")
            else:
                logger.error(f"Failed to send Slack alert: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error sending Slack alert: {e}")

def main():
    parser = argparse.ArgumentParser(description='TapsiFood Dashboard Health Check')
    parser.add_argument('--api-url', default='http://localhost', help='API base URL')
    parser.add_argument('--output', help='Output file for health report')
    parser.add_argument('--alert', action='store_true', help='Send alerts for unhealthy status')
    parser.add_argument('--watch', type=int, help='Run continuously every N seconds')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    
    checker = HealthChecker(args.api_url)
    
    def run_check():
        results = checker.check_all()
        
        if args.json:
            print(json.dumps(results, indent=2, default=str))
        else:
            # Pretty print results
            print(f"\n🏥 Health Check Report - {results['timestamp']}")
            print("=" * 60)
            print(f"Overall Status: {results['overall_status'].upper()}")
            print(f"Health Score: {results['health_score']:.1f}%")
            print("\nDetailed Results:")
            print("-" * 40)
            
            for check_name, result in results['checks'].items():
                status = result.get('status', 'unknown')
                emoji = "✅" if status == 'healthy' else "⚠️" if status == 'warning' else "❌"
                print(f"{emoji} {check_name.replace('_', ' ').title()}: {status}")
                
                if 'message' in result:
                    print(f"   {result['message']}")
                if 'response_time' in result:
                    print(f"   Response time: {result['response_time']:.3f}s")
        
        if args.output:
            checker.save_report(results, args.output)
        
        if args.alert:
            checker.send_alert(results)
        
        return results['overall_status'] != 'healthy'
    
    if args.watch:
        logger.info(f"Starting health monitoring every {args.watch} seconds...")
        try:
            while True:
                has_issues = run_check()
                if not args.json:
                    print(f"\nNext check in {args.watch} seconds... (Ctrl+C to stop)")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            logger.info("Health monitoring stopped")
    else:
        has_issues = run_check()
        sys.exit(1 if has_issues else 0)

if __name__ == '__main__':
    main()