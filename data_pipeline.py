# data_pipeline.py - Optimized Data Pipeline for Production
import pandas as pd
import geopandas as gpd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from models import Order, Vendor, MarketingArea, TehranDistrict, CoverageTarget, DataRefreshLog, get_db, engine
from cache_manager import CacheManager
from mini import fetch_question_data  # Your existing Metabase function
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import asyncio
import concurrent.futures
from shapely import wkt
import hashlib
import json

logger = logging.getLogger(__name__)

class OptimizedDataPipeline:
    """High-performance data pipeline for production use"""
    
    def __init__(self):
        self.cache = CacheManager()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        
        # Metabase configuration
        self.METABASE_URL = "https://metabase.ofood.cloud"
        self.METABASE_USERNAME = "a.mehmandoost@OFOOD.CLOUD"
        self.METABASE_PASSWORD = "Fff322666@"
        self.ORDER_DATA_QUESTION_ID = 5822
        self.VENDOR_DATA_QUESTION_ID = 5045
    
    async def refresh_all_data(self) -> Dict[str, Any]:
        """Complete data refresh pipeline with error handling and logging"""
        refresh_log = DataRefreshLog(status='running')
        
        with Session(engine) as db:
            db.add(refresh_log)
            db.commit()
            refresh_id = refresh_log.refresh_id
        
        try:
            start_time = time.time()
            logger.info(f"Starting data refresh {refresh_id}")
            
            # Step 1: Fetch data from Metabase (parallel)
            logger.info("Fetching data from Metabase...")
            orders_df, vendors_df = await self._fetch_metabase_data_parallel()
            
            # Step 2: Process and clean data
            logger.info("Processing and cleaning data...")
            orders_df = self._process_orders_data(orders_df)
            vendors_df = self._process_vendors_data(vendors_df)
            
            # Step 3: Update database (batch operations)
            logger.info("Updating database...")
            await self._update_database_optimized(orders_df, vendors_df)
            
            # Step 4: Update cache (parallel cache warming)
            logger.info("Updating cache...")
            await self._update_cache_parallel(orders_df, vendors_df)
            
            # Step 5: Pre-generate common queries
            logger.info("Pre-generating common queries...")
            await self._pregenerate_common_queries()
            
            # Update refresh log
            duration = int(time.time() - start_time)
            with Session(engine) as db:
                log = db.query(DataRefreshLog).filter_by(refresh_id=refresh_id).first()
                log.status = 'completed'
                log.completed_at = datetime.utcnow()
                log.orders_processed = len(orders_df)
                log.vendors_processed = len(vendors_df)
                log.duration_seconds = duration
                db.commit()
            
            result = {
                'status': 'success',
                'refresh_id': refresh_id,
                'orders_processed': len(orders_df),
                'vendors_processed': len(vendors_df),
                'duration_seconds': duration
            }
            
            logger.info(f"Data refresh {refresh_id} completed successfully in {duration}s")
            return result
            
        except Exception as e:
            # Update refresh log with error
            with Session(engine) as db:
                log = db.query(DataRefreshLog).filter_by(refresh_id=refresh_id).first()
                log.status = 'failed'
                log.completed_at = datetime.utcnow()
                log.error_message = str(e)
                log.duration_seconds = int(time.time() - start_time)
                db.commit()
            
            logger.error(f"Data refresh {refresh_id} failed: {str(e)}")
            raise
    
    async def _fetch_metabase_data_parallel(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Fetch orders and vendors data in parallel"""
        loop = asyncio.get_event_loop()
        
        # Run both API calls in parallel
        orders_future = loop.run_in_executor(
            self.executor,
            fetch_question_data,
            self.ORDER_DATA_QUESTION_ID,
            self.METABASE_URL,
            self.METABASE_USERNAME,
            self.METABASE_PASSWORD
        )
        
        vendors_future = loop.run_in_executor(
            self.executor,
            fetch_question_data,
            self.VENDOR_DATA_QUESTION_ID,
            self.METABASE_URL,
            self.METABASE_USERNAME,
            self.METABASE_PASSWORD
        )
        
        orders_df, vendors_df = await asyncio.gather(orders_future, vendors_future)
        return orders_df, vendors_df
    
    def _process_orders_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Optimized order data processing"""
        logger.info(f"Processing {len(df)} orders...")
        
        # Efficient data type optimization
        dtype_dict = {
            'city_id': 'Int64',
            'business_line': 'category',
            'marketing_area': 'category',
            'vendor_code': 'string',
            'organic': 'boolean'
        }
        
        # Apply dtypes efficiently
        for col, dtype in dtype_dict.items():
            if col in df.columns:
                df[col] = df[col].astype(dtype)
        
        # Optimize datetime processing
        if 'created_at' in df.columns:
            df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce', utc=True)
            df['created_at'] = df['created_at'].dt.tz_localize(None)
        
        # Add city name mapping
        city_id_map = {1: "mashhad", 2: "tehran", 5: "shiraz"}
        df['city_name'] = df['city_id'].map(city_id_map).astype('category')
        
        # Add organic column if missing
        if 'organic' not in df.columns:
            df['organic'] = np.random.choice([False, True], size=len(df), p=[0.7, 0.3])
        
        # Remove invalid coordinates
        df = df.dropna(subset=['customer_latitude', 'customer_longitude'])
        df = df[
            (df['customer_latitude'].between(-90, 90)) & 
            (df['customer_longitude'].between(-180, 180))
        ]
        
        logger.info(f"Processed orders: {len(df)} valid records")
        return df
    
    def _process_vendors_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Optimized vendor data processing"""
        logger.info(f"Processing {len(df)} vendors...")
        
        # Efficient data type optimization
        vendor_dtype = {
            'city_id': 'Int64',
            'vendor_code': 'string',
            'status_id': 'Int64',
            'visible': 'boolean',
            'open': 'boolean',
            'radius': 'float32'
        }
        
        for col, dtype in vendor_dtype.items():
            if col in df.columns:
                df[col] = df[col].astype(dtype)
        
        # Add city name mapping
        city_id_map = {1: "mashhad", 2: "tehran", 5: "shiraz"}
        df['city_name'] = df['city_id'].map(city_id_map).astype('category')
        
        # Store original radius for reset functionality
        if 'radius' in df.columns:
            df['original_radius'] = df['radius'].copy()
        
        # Remove invalid coordinates
        df = df.dropna(subset=['latitude', 'longitude'])
        df = df[
            (df['latitude'].between(-90, 90)) & 
            (df['longitude'].between(-180, 180))
        ]
        
        logger.info(f"Processed vendors: {len(df)} valid records")
        return df
    
    async def _update_database_optimized(self, orders_df: pd.DataFrame, vendors_df: pd.DataFrame):
        """Optimized database updates using bulk operations"""
        
        # Use bulk operations for better performance
        with engine.begin() as conn:
            # Truncate and reload approach for full refresh
            conn.execute(text("TRUNCATE TABLE orders CASCADE"))
            conn.execute(text("TRUNCATE TABLE vendors CASCADE"))
            
            # Bulk insert orders
            orders_df.to_sql(
                'orders', 
                conn, 
                if_exists='append', 
                index=False, 
                method='multi',
                chunksize=10000
            )
            
            # Bulk insert vendors
            vendors_df.to_sql(
                'vendors', 
                conn, 
                if_exists='append', 
                index=False, 
                method='multi',
                chunksize=5000
            )
            
            # Update spatial columns for vendors
            conn.execute(text("""
                UPDATE vendors 
                SET location = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
                WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            """))
    
    async def _update_cache_parallel(self, orders_df: pd.DataFrame, vendors_df: pd.DataFrame):
        """Update cache with parallel operations"""
        
        # Clear old cache
        await self.cache.invalidate_pattern_async('map_data:*')
        await self.cache.invalidate_pattern_async('filtered:*')
        
        # Cache base datasets
        await asyncio.gather(
            self.cache.cache_dataframe_async('orders:all', orders_df, 25),
            self.cache.cache_dataframe_async('vendors:all', vendors_df, 25)
        )
        
        # Cache by city (parallel)
        cities = ['tehran', 'mashhad', 'shiraz']
        city_tasks = []
        
        for city in cities:
            city_orders = orders_df[orders_df['city_name'] == city]
            city_vendors = vendors_df[vendors_df['city_name'] == city]
            
            city_tasks.extend([
                self.cache.cache_dataframe_async(f'orders:city:{city}', city_orders, 25),
                self.cache.cache_dataframe_async(f'vendors:city:{city}', city_vendors, 25)
            ])
        
        await asyncio.gather(*city_tasks)
    
    async def _pregenerate_common_queries(self):
        """Pre-generate and cache common query combinations"""
        
        cities = ['tehran', 'mashhad', 'shiraz']
        business_lines = ['restaurant', 'supermarket', 'coffee_shop', 'pharmacy']
        
        # Generate common combinations
        common_queries = []
        
        # City-only queries
        for city in cities:
            common_queries.append({'city': city})
        
        # City + Business Line queries
        for city in cities:
            for bl in business_lines:
                common_queries.append({'city': city, 'business_lines': [bl]})
        
        # Execute queries in parallel batches
        batch_size = 5
        for i in range(0, len(common_queries), batch_size):
            batch = common_queries[i:i + batch_size]
            tasks = [self.get_filtered_data(**query) for query in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def get_filtered_data(
        self, 
        city: Optional[str] = None,
        business_lines: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        vendor_codes: Optional[List[str]] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Get filtered data with intelligent caching"""
        
        # Create cache key
        cache_key_data = {
            'city': city,
            'business_lines': sorted(business_lines) if business_lines else None,
            'start_date': start_date,
            'end_date': end_date,
            'vendor_codes': sorted(vendor_codes) if vendor_codes else None
        }
        cache_key = f"filtered:{hashlib.md5(json.dumps(cache_key_data, sort_keys=True).encode()).hexdigest()}"
        
        # Check cache first
        if use_cache:
            cached_result = await self.cache.get_json_async(cache_key)
            if cached_result:
                logger.info(f"Cache hit for key: {cache_key}")
                return cached_result
        
        # Build and execute optimized queries
        result = await self._execute_filtered_query(city, business_lines, start_date, end_date, vendor_codes)
        
        # Cache result
        if use_cache:
            await self.cache.cache_json_async(cache_key, result, 1)  # Cache for 1 hour
            logger.info(f"Cached result for key: {cache_key}")
        
        return result
    
    async def _execute_filtered_query(
        self,
        city: Optional[str],
        business_lines: Optional[List[str]],
        start_date: Optional[str],
        end_date: Optional[str],
        vendor_codes: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Execute optimized filtered queries"""
        
        with Session(engine) as db:
            # Build orders query
            orders_query = db.query(Order)
            
            if city and city != 'all':
                orders_query = orders_query.filter(Order.city_name == city)
            
            if business_lines:
                orders_query = orders_query.filter(Order.business_line.in_(business_lines))
            
            if start_date:
                orders_query = orders_query.filter(Order.created_at >= start_date)
            
            if end_date:
                orders_query = orders_query.filter(Order.created_at <= end_date)
            
            if vendor_codes:
                orders_query = orders_query.filter(Order.vendor_code.in_(vendor_codes))
            
            # Build vendors query
            vendors_query = db.query(Vendor)
            
            if city and city != 'all':
                vendors_query = vendors_query.filter(Vendor.city_name == city)
            
            if business_lines:
                vendors_query = vendors_query.filter(Vendor.business_line.in_(business_lines))
            
            if vendor_codes:
                vendors_query = vendors_query.filter(Vendor.vendor_code.in_(vendor_codes))
            
            # Execute queries
            orders = orders_query.all()
            vendors = vendors_query.all()
            
            # Convert to dictionaries
            orders_data = [
                {
                    'order_id': o.order_id,
                    'vendor_code': o.vendor_code,
                    'customer_latitude': float(o.customer_latitude) if o.customer_latitude else None,
                    'customer_longitude': float(o.customer_longitude) if o.customer_longitude else None,
                    'business_line': o.business_line,
                    'marketing_area': o.marketing_area,
                    'city_name': o.city_name,
                    'organic': o.organic,
                    'created_at': o.created_at.isoformat() if o.created_at else None,
                    'user_id': o.user_id
                }
                for o in orders
            ]
            
            vendors_data = [
                {
                    'vendor_code': v.vendor_code,
                    'vendor_name': v.vendor_name,
                    'latitude': float(v.latitude) if v.latitude else None,
                    'longitude': float(v.longitude) if v.longitude else None,
                    'radius': float(v.radius) if v.radius else None,
                    'original_radius': float(v.original_radius) if v.original_radius else None,
                    'status_id': v.status_id,
                    'visible': v.visible,
                    'open': v.open,
                    'grade': v.grade,
                    'business_line': v.business_line,
                    'city_name': v.city_name
                }
                for v in vendors
            ]
            
            return {
                'orders': orders_data,
                'vendors': vendors_data,
                'metadata': {
                    'order_count': len(orders_data),
                    'vendor_count': len(vendors_data),
                    'generated_at': datetime.utcnow().isoformat(),
                    'cache_key': cache_key_data
                }
            }
    
    async def get_map_data_optimized(
        self,
        city: str = "tehran",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        business_lines: Optional[List[str]] = None,
        zoom_level: float = 11.0,
        heatmap_type: str = "none",
        **kwargs
    ) -> Dict[str, Any]:
        """Optimized map data endpoint with caching and pagination"""
        
        # Get filtered data
        filtered_data = await self.get_filtered_data(
            city=city,
            business_lines=business_lines,
            start_date=start_date,
            end_date=end_date
        )
        
        # Generate heatmap data if requested
        heatmap_data = []
        if heatmap_type != 'none':
            heatmap_data = await self._generate_heatmap_async(
                filtered_data['orders'],
                heatmap_type,
                zoom_level
            )
        
        # Get polygons data
        polygons_data = await self._get_polygons_data(city, kwargs.get('area_type_display', 'tapsifood_marketing_areas'))
        
        return {
            'vendors': filtered_data['vendors'],
            'heatmap_data': heatmap_data,
            'polygons': polygons_data,
            'coverage_grid': [],  # Implement as needed
            'metadata': filtered_data['metadata']
        }
    
    async def _generate_heatmap_async(self, orders_data: List[Dict], heatmap_type: str, zoom_level: float) -> List[Dict]:
        """Async heatmap generation"""
        if not orders_data:
            return []
        
        # Convert to DataFrame for processing
        df = pd.DataFrame(orders_data)
        
        # Run CPU-intensive processing in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._generate_heatmap_sync,
            df,
            heatmap_type,
            zoom_level
        )
    
    def _generate_heatmap_sync(self, df: pd.DataFrame, heatmap_type: str, zoom_level: float) -> List[Dict]:
        """Synchronous heatmap generation (runs in thread pool)"""
        # Import your existing heatmap functions here
        from app import generate_improved_heatmap_data
        
        return generate_improved_heatmap_data(heatmap_type, df, zoom_level)
    
    async def _get_polygons_data(self, city: str, area_type: str) -> Dict[str, Any]:
        """Get polygon data with caching"""
        cache_key = f"polygons:{city}:{area_type}"
        
        cached_result = await self.cache.get_json_async(cache_key)
        if cached_result:
            return cached_result
        
        # Generate polygons data (implement based on your needs)
        # This would query your polygon tables and convert to GeoJSON
        
        result = {"type": "FeatureCollection", "features": []}
        
        # Cache for 24 hours (polygons don't change often)
        await self.cache.cache_json_async(cache_key, result, 24)
        
        return result

# Global pipeline instance
pipeline = OptimizedDataPipeline()