# 🚀 Complete Production Deployment Guide
## TapsiFood Dashboard v2.0 - Production Deployment

---

## 📋 **Prerequisites Checklist**

### **Server Requirements**
- [ ] **CPU**: 4+ cores (8+ recommended)
- [ ] **RAM**: 8GB minimum (16GB+ recommended)
- [ ] **Storage**: 100GB+ SSD
- [ ] **OS**: Ubuntu 20.04+ / CentOS 8+ / Docker-compatible OS
- [ ] **Network**: Port 80, 443, 22 accessible

### **Software Requirements**
- [ ] **Docker**: v20.10+
- [ ] **Docker Compose**: v2.0+
- [ ] **Git**: Latest version
- [ ] **Make**: For automation scripts
- [ ] **curl/wget**: For health checks

### **Access Requirements**
- [ ] **Metabase API**: Credentials and access
- [ ] **Server Access**: SSH with sudo privileges
- [ ] **Domain**: Optional but recommended for SSL
- [ ] **Email/Slack**: For alerts (optional)

---

## 🏗️ **Phase 1: Server Setup and Dependencies**

### **Step 1.1: Update System**
```bash
# Update package lists and system
sudo apt update && sudo apt upgrade -y

# Install essential packages
sudo apt install -y curl wget git make unzip software-properties-common apt-transport-https ca-certificates gnupg lsb-release
```

### **Step 1.2: Install Docker**
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version

# Start Docker service
sudo systemctl enable docker
sudo systemctl start docker
```

### **Step 1.3: Configure System Limits**
```bash
# Increase file limits for high-performance apps
echo "* soft nofile 65536" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 65536" | sudo tee -a /etc/security/limits.conf

# Configure kernel parameters
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf
echo "net.core.somaxconn=1024" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

---

## 📦 **Phase 2: Application Deployment**

### **Step 2.1: Clone and Setup Repository**
```bash
# Create application directory
sudo mkdir -p /opt/tapsifood-dashboard
sudo chown $USER:$USER /opt/tapsifood-dashboard
cd /opt/tapsifood-dashboard

# Clone your repository (replace with actual repo URL)
git clone https://github.com/your-org/tapsifood-dashboard-production.git .

# Make scripts executable
chmod +x docker/entrypoint.sh
chmod +x docker/worker-entrypoint.sh
chmod +x scripts/*.py
```

### **Step 2.2: Configure Environment**
```bash
# Copy and configure environment file
cp .env.example .env

# Edit the configuration file
nano .env
```

**Required Environment Variables:**
```bash
# Database
DB_PASSWORD=your_very_secure_password_here
SECRET_KEY=your_super_secret_key_minimum_32_characters

# Metabase API
METABASE_URL=https://metabase.ofood.cloud
METABASE_USERNAME=your_username
METABASE_PASSWORD=your_password

# Domain (if using SSL)
DOMAIN_NAME=your-domain.com

# Email alerts (optional)
EMAIL_HOST_USER=alerts@yourdomain.com
EMAIL_HOST_PASSWORD=your_email_password
ALERT_EMAIL_RECIPIENTS=admin@yourdomain.com

# Slack alerts (optional)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK
```

### **Step 2.3: Build and Deploy**
```bash
# Build Docker images
make build

# Deploy services
make deploy-services

# Wait for services to start (this may take 2-3 minutes)
sleep 120

# Check service status
make status
```

---

## 🗄️ **Phase 3: Database Setup**

### **Step 3.1: Initialize Database**
```bash
# Run complete database setup
make init-db

# This will:
# - Create all tables with optimized indexes
# - Load polygon data from shapefiles
# - Set up coverage targets
# - Verify installation
```

### **Step 3.2: Migrate Data from Old System**
```bash
# Option A: Fresh data from Metabase (recommended)
make migrate-db

# Option B: If you have CSV exports from old system
# Place CSV files in data/ directory, then:
python scripts/init_db.py --migrate-data

# Verify data migration
make verify-db
```

### **Step 3.3: Setup Data Refresh Schedule**
```bash
# The system automatically schedules data refresh at 9 AM
# Verify Celery beat is running
docker-compose -f docker-compose.prod.yml logs scheduler

# Manually trigger a test refresh
make refresh-data

# Check refresh status
curl http://localhost/api/v2/health
```

---

## 🚀 **Phase 4: Production Validation**

### **Step 4.1: Health Checks**
```bash
# Run comprehensive health check
make health-check

# Check all services
make status

# Test API endpoints
curl http://localhost/api/v2/health
curl http://localhost/api/v2/initial-data
```

### **Step 4.2: Performance Testing**
```bash
# Test with multiple concurrent users
make load-test

# Run benchmark
make benchmark

# Monitor resource usage
docker stats
```

### **Step 4.3: Access Dashboard**
```bash
# Open dashboard in browser
# If running locally: http://localhost
# If on server: http://your-server-ip

# Test all major features:
# - Map loading
# - Filter changes
# - Heatmap generation
# - Vendor display
# - Coverage grid (if applicable)
```

---

## 🔒 **Phase 5: Security and SSL Setup**

### **Step 5.1: Setup SSL (Optional but Recommended)**
```bash
# If you have a domain name, set up SSL
make setup-ssl

# Or manually with Let's Encrypt
sudo apt install certbot
sudo certbot certonly --standalone -d your-domain.com

# Copy certificates to ssl directory
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ssl/cert.pem
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem ssl/key.pem
sudo chown $USER:$USER ssl/*.pem

# Update environment
echo "SSL_ENABLED=true" >> .env
echo "DOMAIN_NAME=your-domain.com" >> .env

# Restart services
make restart
```

### **Step 5.2: Configure Firewall**
```bash
# Configure UFW firewall
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS (if SSL enabled)
sudo ufw deny 5432/tcp   # Block external database access
sudo ufw deny 6379/tcp   # Block external Redis access
sudo ufw enable

# Verify firewall status
sudo ufw status
```

---

## 📊 **Phase 6: Monitoring Setup**

### **Step 6.1: Enable Monitoring Stack**
```bash
# Deploy with monitoring (Prometheus + Grafana)
make deploy-prod

# Access monitoring dashboards:
# Grafana: http://localhost:3000 (admin/admin)
# Prometheus: http://localhost:9090
```

### **Step 6.2: Configure Alerts**
```bash
# Set up email alerts in .env
EMAIL_ENABLED=true
EMAIL_HOST=smtp.gmail.com
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
ALERT_EMAIL_RECIPIENTS=admin@yourdomain.com

# Set up Slack alerts
SLACK_ENABLED=true
SLACK_WEBHOOK_URL=your-slack-webhook-url

# Restart services to apply changes
make restart
```

### **Step 6.3: Log Management**
```bash
# View logs
make logs                # All services
make logs-web           # Web services only
make logs-worker        # Background workers only

# Set up log rotation
sudo nano /etc/logrotate.d/tapsifood-dashboard
```

Add to logrotate config:
```
/opt/tapsifood-dashboard/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    copytruncate
    create 644 root root
}
```

---

## 🔄 **Phase 7: Operations and Maintenance**

### **Step 7.1: Backup Setup**
```bash
# Set up automated backups
echo "BACKUP_ENABLED=true" >> .env
echo "BACKUP_RETENTION_DAYS=30" >> .env

# Create backup directory
sudo mkdir -p /opt/backups/tapsifood-dashboard
sudo chown $USER:$USER /opt/backups/tapsifood-dashboard

# Test backup
make backup

# Set up cron for daily backups
crontab -e
```

Add to crontab:
```
0 2 * * * cd /opt/tapsifood-dashboard && make backup >> /var/log/tapsifood-backup.log 2>&1
```

### **Step 7.2: Update Procedures**
```bash
# Create update script
cat > update-dashboard.sh << 'EOF'
#!/bin/bash
set -e

echo "🔄 Starting dashboard update..."

# Pull latest changes
git pull origin main

# Rebuild images
make build-no-cache

# Restart services with zero downtime
make restart-web
sleep 30
make restart-workers

# Verify health
make health-check

echo "✅ Update completed successfully"
EOF

chmod +x update-dashboard.sh
```

### **Step 7.3: Scaling Configuration**
```bash
# Scale web services for high load
REPLICAS=5 make scale

# Add more workers for background processing
docker-compose -f docker-compose.prod.yml up -d --scale worker=4

# Monitor performance
watch docker stats
```

---

## 🚨 **Phase 8: Troubleshooting Guide**

### **Common Issues and Solutions**

#### **Issue: Services won't start**
```bash
# Check Docker status
sudo systemctl status docker

# Check service logs
docker-compose -f docker-compose.prod.yml logs

# Check system resources
df -h
free -h
```

#### **Issue: Database connection fails**
```bash
# Check PostgreSQL logs
make logs-db

# Verify database credentials
docker-compose -f docker-compose.prod.yml exec postgres psql -U dashboard_user -d tapsifood_dashboard -c "SELECT version();"

# Reset database if needed
docker-compose -f docker-compose.prod.yml down -v
make deploy-services
make init-db
```

#### **Issue: Data refresh fails**
```bash
# Check worker logs
make logs-worker

# Check Metabase connectivity
curl -I https://metabase.ofood.cloud

# Manually trigger refresh with debugging
python scripts/debug_refresh.py
```

#### **Issue: High memory usage**
```bash
# Check Redis memory
docker-compose -f docker-compose.prod.yml exec redis redis-cli info memory

# Clear cache if needed
make clear-cache

# Restart services
make restart
```

#### **Issue: Slow performance**
```bash
# Check cache hit rate
curl http://localhost/api/v2/metrics

# Warm cache
make warm-cache

# Check database performance
docker-compose -f docker-compose.prod.yml exec postgres psql -U dashboard_user -d tapsifood_dashboard -c "SELECT * FROM pg_stat_activity;"
```

---

## 📈 **Phase 9: Performance Optimization**

### **Database Optimization**
```bash
# Add additional indexes for your specific queries
docker-compose -f docker-compose.prod.yml exec postgres psql -U dashboard_user -d tapsifood_dashboard << 'EOF'
-- Add custom indexes based on your query patterns
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_custom ON orders(city_name, created_at, business_line);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vendors_custom ON vendors(city_name, status_id, visible);
EOF
```

### **Cache Optimization**
```bash
# Increase Redis memory if needed
echo "REDIS_MAXMEMORY=2gb" >> .env

# Optimize cache TTL settings
echo "CACHE_TTL_MAP_DATA=7200" >> .env  # 2 hours
echo "CACHE_TTL_HEATMAP_DATA=7200" >> .env  # 2 hours

# Restart Redis
docker-compose -f docker-compose.prod.yml restart redis
```

### **Application Optimization**
```bash
# Increase worker count for high load
echo "WORKERS=8" >> .env
echo "CELERY_WORKER_PROCESSES=6" >> .env

# Optimize database connections
echo "DB_POOL_SIZE=30" >> .env
echo "DB_MAX_OVERFLOW=40" >> .env

# Restart services
make restart
```

---

## ✅ **Phase 10: Production Checklist**

### **Pre-Go-Live Checklist**
- [ ] All services running and healthy
- [ ] Database properly migrated and indexed
- [ ] Cache hit rate > 80%
- [ ] SSL certificates configured (if applicable)
- [ ] Monitoring and alerts working
- [ ] Backups configured and tested
- [ ] Load testing completed successfully
- [ ] Documentation updated
- [ ] Team trained on operations

### **Go-Live Checklist**
- [ ] DNS updated (if using custom domain)
- [ ] Load balancer configured
- [ ] Monitoring dashboards accessible
- [ ] Alert channels tested
- [ ] Rollback plan documented
- [ ] Support team notified

### **Post-Go-Live Checklist**
- [ ] Performance monitoring for 24 hours
- [ ] Daily data refresh working
- [ ] User feedback collected
- [ ] Performance metrics baseline established
- [ ] Incident response procedures tested

---

## 📞 **Support and Maintenance**

### **Daily Operations**
```bash
# Morning checklist (automated via cron)
0 9 * * * cd /opt/tapsifood-dashboard && make health-check
0 10 * * * cd /opt/tapsifood-dashboard && curl -s http://localhost/api/v2/metrics | mail -s "Dashboard Metrics" admin@yourdomain.com
```

### **Weekly Maintenance**
```bash
# Weekly maintenance script
cat > weekly-maintenance.sh << 'EOF'
#!/bin/bash
echo "🔧 Weekly maintenance starting..."

# Update system packages
sudo apt update && sudo apt upgrade -y

# Clean Docker resources
docker system prune -f

# Rotate logs
sudo logrotate -f /etc/logrotate.d/tapsifood-dashboard

# Restart services for fresh state
make restart

# Generate weekly report
curl -s http://localhost/api/v2/admin/reports/weekly | python -m json.tool > weekly-report-$(date +%Y%m%d).json

echo "✅ Weekly maintenance completed"
EOF

chmod +x weekly-maintenance.sh
```

### **Emergency Procedures**
```bash
# Create emergency procedures document
cat > EMERGENCY_PROCEDURES.md << 'EOF'
# 🚨 Emergency Procedures

## Service Down
1. Check service status: `make status`
2. Check logs: `make logs`
3. Restart services: `make restart`
4. If still failing: `make clean && make deploy`

## Database Issues
1. Check database logs: `make logs-db`
2. Check connections: `docker-compose exec postgres psql -U dashboard_user -d tapsifood_dashboard -c "SELECT 1"`
3. If corrupted: Restore from backup: `make restore BACKUP_FILE=backup_YYYYMMDD_HHMMSS.sql`

## High Load
1. Scale web services: `REPLICAS=10 make scale`
2. Add more workers: `docker-compose up -d --scale worker=6`
3. Clear cache if needed: `make clear-cache`
4. Monitor: `watch docker stats`

## Contact Information
- Primary: admin@yourdomain.com
- Secondary: devops@yourdomain.com
- Slack: #dashboard-alerts
EOF
```

---

## 🎉 **Success! Your TapsiFood Dashboard is Production Ready**

### **Expected Performance Metrics**
- **Response Time**: 200-500ms (cached requests)
- **Concurrent Users**: 100+ simultaneous users
- **Data Freshness**: Automatic daily refresh at 9 AM
- **Uptime**: 99.9%+ availability
- **Cache Hit Rate**: 85%+ for optimal performance

### **Next Steps**
1. **Monitor Performance**: Watch metrics for first 48 hours
2. **Gather Feedback**: Collect user feedback for improvements
3. **Optimize Further**: Fine-tune based on actual usage patterns
4. **Scale as Needed**: Add more resources based on demand
5. **Regular Updates**: Keep system updated and secure

### **Support Resources**
- **Health Dashboard**: http://your-domain/api/v2/health
- **Metrics**: http://your-domain/api/v2/metrics
- **Grafana**: http://your-domain:3000 (if monitoring enabled)
- **Logs**: `make logs` for troubleshooting

---

**🚀 Congratulations! Your production-grade TapsiFood Dashboard is now live and serving users with enterprise-level performance and reliability!**