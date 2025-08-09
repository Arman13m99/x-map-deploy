# api.py - Production FastAPI Application
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import time
import logging
import os
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uvicorn

# Import our optimized modules
from data_pipeline import OptimizedDataPipeline
from cache_manager import CacheManager
from models import get_db, DataRefreshLog
from tasks import refresh_all_data, warm_cache, health_check

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="TapsiFood Dashboard API",
    description="High-performance API for TapsiFood business intelligence dashboard",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Global instances
pipeline = OptimizedDataPipeline()
cache = CacheManager()

# Serve static files (your existing frontend)
app.mount("/static", StaticFiles(directory="public"), name="static")

# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    
    # Log slow requests
    if process_time > 2.0:
        logger.warning(f"Slow request: {request.url} took {process_time:.2f}s")
    
    return response

# Health check endpoints
@app.get("/api/v2/health")
async def health_check_endpoint():
    """Comprehensive health check"""
    try:
        # Check database
        db_healthy = True
        try:
            from models import engine
            with engine.connect() as conn:
                conn.execute("SELECT 1")
        except Exception as e:
            db_healthy = False
            logger.error(f"Database health check failed: {e}")
        
        # Check cache
        cache_healthy = True
        try:
            cache.redis_client.ping()
        except Exception as e:
            cache_healthy = False
            logger.error(f"Cache health check failed: {e}")
        
        # Check last data refresh
        last_refresh = None
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT started_at, status, duration_seconds 
                    FROM data_refresh_logs 
                    ORDER BY started_at DESC 
                    LIMIT 1
                """)).fetchone()
                if result:
                    last_refresh = {
                        'started_at': result.started_at.isoformat(),
                        'status': result.status,
                        'duration_seconds': result.duration_seconds
                    }
        except Exception as e:
            logger.error(f"Last refresh check failed: {e}")
        
        overall_healthy = db_healthy and cache_healthy
        status_code = 200 if overall_healthy else 503
        
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "healthy" if overall_healthy else "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
                "services": {
                    "database": "healthy" if db_healthy else "unhealthy",
                    "cache": "healthy" if cache_healthy else "unhealthy"
                },
                "last_data_refresh": last_refresh,
                "version": "2.0.0"
            }
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.get("/api/v2/metrics")
async def get_metrics():
    """Get system performance metrics"""
    try:
        cache_stats = cache.get_cache_stats()
        
        # Get recent refresh logs
        from models import engine
        from sqlalchemy import text
        
        with engine.connect() as conn:
            recent_refreshes = conn.execute(text("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
                       AVG(duration_seconds) as avg_duration
                FROM data_refresh_logs 
                WHERE started_at >= NOW() - INTERVAL '7 days'
            """)).fetchone()
        
        return {
            "cache_metrics": cache_stats,
            "data_refresh_metrics": {
                "last_7_days_total": recent_refreshes.total,
                "last_7_days_successful": recent_refreshes.successful,
                "average_duration_seconds": recent_refreshes.avg_duration,
                "success_rate": (recent_refreshes.successful / max(recent_refreshes.total, 1)) * 100
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Metrics collection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Data endpoints
@app.get("/api/v2/initial-data")
async def get_initial_data():
    """Get initial filter options and metadata"""
    try:
        # Try cache first
        cached_data = cache.get_json("initial_data")
        if cached_data:
            return cached_data
        
        # Generate initial data
        from models import engine
        from sqlalchemy import text
        
        with engine.connect() as conn:
            # Get cities
            cities_result = conn.execute(text("""
                SELECT DISTINCT city_id, city_name 
                FROM vendors 
                WHERE city_name IS NOT NULL 
                ORDER BY city_name
            """)).fetchall()
            
            cities = [{"id": r.city_id, "name": r.city_name} for r in cities_result]
            
            # Get business lines
            bl_result = conn.execute(text("""
                SELECT DISTINCT business_line 
                FROM orders 
                WHERE business_line IS NOT NULL 
                ORDER BY business_line
            """)).fetchall()
            
            business_lines = [r.business_line for r in bl_result]
            
            # Get vendor statuses
            status_result = conn.execute(text("""
                SELECT DISTINCT status_id 
                FROM vendors 
                WHERE status_id IS NOT NULL 
                ORDER BY status_id
            """)).fetchall()
            
            vendor_statuses = [r.status_id for r in status_result]
            
            # Get vendor grades
            grade_result = conn.execute(text("""
                SELECT DISTINCT grade 
                FROM vendors 
                WHERE grade IS NOT NULL 
                ORDER BY grade
            """)).fetchall()
            
            vendor_grades = [r.grade for r in grade_result]
        
        initial_data = {
            "cities": cities,
            "business_lines": business_lines,
            "vendor_statuses": vendor_statuses,
            "vendor_grades": vendor_grades,
            "marketing_areas_by_city": {},  # Implement as needed
            "tehran_region_districts": [],   # Implement as needed
            "tehran_main_districts": []      # Implement as needed
        }
        
        # Cache for 6 hours
        cache.cache_json("initial_data", initial_data, 6)
        
        return initial_data
        
    except Exception as e:
        logger.error(f"Initial data fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v2/map-data")
async def get_map_data_v2(
    city: str = Query("tehran"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    business_lines: List[str] = Query(default=[]),
    vendor_codes_filter: Optional[str] = None,
    zoom_level: float = Query(11.0),
    heatmap_type_request: str = Query("none"),
    area_type_display: str = Query("tapsifood_marketing_areas"),
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=5000)
):
    """
    Optimized map data endpoint with pagination and caching
    """
    try:
        # Parse vendor codes
        vendor_codes = []
        if vendor_codes_filter:
            vendor_codes = [code.strip() for code in vendor_codes_filter.replace('\n', ',').split(',') if code.strip()]
        
        # Get filtered data from pipeline
        filtered_data = await pipeline.get_filtered_data(
            city=city if city != "all" else None,
            business_lines=business_lines if business_lines else None,
            start_date=start_date,
            end_date=end_date,
            vendor_codes=vendor_codes if vendor_codes else None
        )
        
        # Apply pagination to vendors
        total_vendors = len(filtered_data['vendors'])
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_vendors = filtered_data['vendors'][start_idx:end_idx]
        
        # Generate heatmap data if requested
        heatmap_data = []
        if heatmap_type_request != 'none':
            heatmap_data = await pipeline._generate_heatmap_async(
                filtered_data['orders'],
                heatmap_type_request,
                zoom_level
            )
        
        # Get polygons data
        polygons_data = await pipeline._get_polygons_data(city, area_type_display)
        
        response_data = {
            "vendors": paginated_vendors,
            "heatmap_data": heatmap_data,
            "polygons": polygons_data,
            "coverage_grid": [],  # Implement coverage grid as needed
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_vendors": total_vendors,
                "total_pages": (total_vendors + page_size - 1) // page_size,
                "has_next": end_idx < total_vendors,
                "has_previous": page > 1
            },
            "metadata": {
                **filtered_data['metadata'],
                "zoom_level": zoom_level,
                "heatmap_type": heatmap_type_request
            }
        }
        
        return response_data
        
    except Exception as e:
        logger.error(f"Map data fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Admin endpoints
@app.post("/api/v2/admin/refresh-data")
async def trigger_data_refresh(background_tasks: BackgroundTasks):
    """Manually trigger data refresh"""
    try:
        # Trigger background task
        task = refresh_all_data.delay()
        
        return {
            "status": "triggered",
            "task_id": task.id,
            "message": "Data refresh has been queued",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Manual refresh trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v2/admin/warm-cache")
async def trigger_cache_warming(background_tasks: BackgroundTasks):
    """Manually trigger cache warming"""
    try:
        task = warm_cache.delay()
        
        return {
            "status": "triggered",
            "task_id": task.id,
            "message": "Cache warming has been queued",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Cache warming trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v2/admin/cache")
async def clear_cache(pattern: str = Query("*")):
    """Clear cache entries matching pattern"""
    try:
        deleted_count = cache.invalidate_pattern(pattern)
        
        return {
            "status": "success",
            "deleted_keys": deleted_count,
            "pattern": pattern,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Cache clearing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v2/admin/reports/daily")
async def get_daily_report(date: Optional[str] = None):
    """Get daily performance report"""
    try:
        if date:
            report = cache.get_json(f"daily_report:{date}")
        else:
            report = cache.get_json("daily_report:latest")
        
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        return report
        
    except Exception as e:
        logger.error(f"Daily report fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Backward compatibility - serve original app
@app.get("/")
async def serve_index():
    """Serve the main dashboard page"""
    from fastapi.responses import FileResponse
    return FileResponse("public/index.html")

@app.get("/api/initial-data")
async def get_initial_data_v1():
    """Backward compatibility endpoint"""
    return await get_initial_data()

@app.get("/api/map-data")
async def get_map_data_v1(request: Request):
    """Backward compatibility endpoint"""
    # Extract query parameters
    query_params = dict(request.query_params)
    
    # Convert to new format
    business_lines = query_params.get('business_lines', '').split(',') if query_params.get('business_lines') else []
    
    return await get_map_data_v2(
        city=query_params.get('city', 'tehran'),
        start_date=query_params.get('start_date'),
        end_date=query_params.get('end_date'),
        business_lines=business_lines,
        vendor_codes_filter=query_params.get('vendor_codes_filter'),
        zoom_level=float(query_params.get('zoom_level', 11.0)),
        heatmap_type_request=query_params.get('heatmap_type_request', 'none'),
        area_type_display=query_params.get('area_type_display', 'tapsifood_marketing_areas')
    )

# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": "The requested resource was not found",
            "path": str(request.url.path)
        }
    )

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception):
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("🚀 Starting TapsiFood Dashboard API v2.0.0")
    
    # Verify database connection
    try:
        from models import engine
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        logger.info("✅ Database connection verified")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
    
    # Verify cache connection
    try:
        cache.redis_client.ping()
        logger.info("✅ Cache connection verified")
    except Exception as e:
        logger.error(f"❌ Cache connection failed: {e}")
    
    logger.info("🎯 API ready to serve requests")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("🛑 Shutting down TapsiFood Dashboard API")
    
    # Close cache connections
    try:
        await cache.close()
        logger.info("✅ Cache connections closed")
    except Exception as e:
        logger.error(f"❌ Cache cleanup failed: {e}")
    
    logger.info("👋 API shutdown complete")

# Development server
if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )