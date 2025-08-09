# scripts/init_db.py - Database Initialization and Migration Script
import os
import sys
import pandas as pd
import geopandas as gpd
from shapely import wkt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import logging
from datetime import datetime
import argparse

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from models import Base, Order, Vendor, MarketingArea, TehranDistrict, CoverageTarget, engine
from data_pipeline import OptimizedDataPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseInitializer:
    """Database initialization and data migration"""
    
    def __init__(self):
        self.engine = engine
        
    def create_tables(self):
        """Create all database tables"""
        logger.info("Creating database tables...")
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("✅ Database tables created successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create tables: {e}")
            raise
    
    def drop_tables(self):
        """Drop all tables (use with caution!)"""
        logger.info("Dropping all database tables...")
        try:
            Base.metadata.drop_all(bind=self.engine)
            logger.info("✅ Database tables dropped successfully")
        except Exception as e:
            logger.error(f"❌ Failed to drop tables: {e}")
            raise
    
    def create_indexes(self):
        """Create additional optimized indexes"""
        logger.info("Creating additional database indexes...")
        
        additional_indexes = [
            # Composite indexes for common query patterns
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_city_date_business ON orders(city_name, created_at, business_line);",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_vendor_date ON orders(vendor_code, created_at);",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_user_date ON orders(user_id, created_at);",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vendors_city_grade_status ON vendors(city_name, grade, status_id);",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vendors_business_visible ON vendors(business_line, visible, open);",
            
            # Partial indexes for common filters
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_recent ON orders(created_at) WHERE created_at >= NOW() - INTERVAL '90 days';",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vendors_active ON vendors(vendor_code) WHERE visible = true AND open = true;",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_organic ON orders(created_at, city_name) WHERE organic = true;",
            
            # Full-text search indexes
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vendors_name_search ON vendors USING gin(to_tsvector('english', vendor_name));",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_marketing_areas_name_search ON marketing_areas USING gin(to_tsvector('english', name));"
        ]
        
        try:
            with self.engine.connect() as conn:
                for index_sql in additional_indexes:
                    try:
                        logger.info(f"Creating index: {index_sql[:50]}...")
                        conn.execute(text(index_sql))
                        conn.commit()
                    except Exception as e:
                        logger.warning(f"Index creation failed (might already exist): {e}")
            
            logger.info("✅ Additional indexes created successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create indexes: {e}")
            raise
    
    def load_polygon_data(self):
        """Load polygon data from shapefiles"""
        logger.info("Loading polygon data...")
        
        try:
            # Load marketing areas
            self._load_marketing_areas()
            
            # Load Tehran districts
            self._load_tehran_districts()
            
            # Load coverage targets
            self._load_coverage_targets()
            
            logger.info("✅ Polygon data loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load polygon data: {e}")
            raise
    
    def _load_marketing_areas(self):
        """Load marketing areas from CSV files"""
        marketing_areas_base = os.path.join(os.path.dirname(__file__), '..', 'data', 'polygons', 'tapsifood_marketing_areas')
        
        with Session(self.engine) as db:
            for city_file in ['mashhad_polygons.csv', 'tehran_polygons.csv', 'shiraz_polygons.csv']:
                city_name = city_file.split('_')[0]
                file_path = os.path.join(marketing_areas_base, city_file)
                
                if not os.path.exists(file_path):
                    logger.warning(f"Marketing areas file not found: {file_path}")
                    continue
                
                try:
                    df_poly = pd.read_csv(file_path, encoding='utf-8')
                    
                    for idx, row in df_poly.iterrows():
                        area = MarketingArea(
                            area_id=f"{city_name}_{idx}",
                            name=row.get('name', f"{city_name}_area_{idx}"),
                            city_name=city_name,
                            geometry_wkt=row.get('WKT'),
                            geometry=wkt.loads(row['WKT']) if pd.notna(row.get('WKT')) else None
                        )
                        db.merge(area)
                    
                    db.commit()
                    logger.info(f"✅ Loaded {len(df_poly)} marketing areas for {city_name}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to load marketing areas for {city_name}: {e}")
                    db.rollback()
    
    def _load_tehran_districts(self):
        """Load Tehran district data from shapefiles"""
        districts_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polygons', 'tehran_districts')
        
        district_files = [
            ('RegionTehran_WGS1984.shp', 'region'),
            ('Tehran_WGS1984.shp', 'main')
        ]
        
        with Session(self.engine) as db:
            for shapefile, district_type in district_files:
                file_path = os.path.join(districts_path, shapefile)
                
                if not os.path.exists(file_path):
                    logger.warning(f"Tehran districts file not found: {file_path}")
                    continue
                
                try:
                    gdf = gpd.read_file(file_path)
                    
                    # Reproject to WGS84 if needed
                    if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
                        gdf = gdf.to_crs("EPSG:4326")
                    
                    for idx, row in gdf.iterrows():
                        # Determine name column
                        name = None
                        for name_col in ['Name', 'NAME_MAHAL', 'NAME_1', 'NAME_2', 'district']:
                            if name_col in row and pd.notna(row[name_col]):
                                name = str(row[name_col]).strip()
                                break
                        
                        if not name:
                            name = f"{district_type}_district_{idx}"
                        
                        district = TehranDistrict(
                            district_id=f"{district_type}_{idx}",
                            name=name,
                            district_type=district_type,
                            population=int(row['Pop']) if 'Pop' in row and pd.notna(row['Pop']) else None,
                            population_density=float(row['PopDensity']) if 'PopDensity' in row and pd.notna(row['PopDensity']) else None,
                            geometry_wkt=row.geometry.wkt if row.geometry else None,
                            geometry=row.geometry
                        )
                        db.merge(district)
                    
                    db.commit()
                    logger.info(f"✅ Loaded {len(gdf)} {district_type} districts")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to load {district_type} districts: {e}")
                    db.rollback()
    
    def _load_coverage_targets(self):
        """Load coverage targets from CSV"""
        targets_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'targets', 'tehran_coverage.csv')
        
        if not os.path.exists(targets_file):
            logger.warning(f"Coverage targets file not found: {targets_file}")
            return
        
        try:
            df_targets = pd.read_csv(targets_file, encoding='utf-8')
            
            # Get marketing area mapping
            with Session(self.engine) as db:
                tehran_areas = db.query(MarketingArea).filter_by(city_name='tehran').all()
                area_name_to_id = {area.name: area.area_id for area in tehran_areas}
                
                # Melt the dataframe to long format
                df_melted = df_targets.melt(
                    id_vars=['marketing_area'],
                    var_name='business_line',
                    value_name='target_value'
                )
                
                for _, row in df_melted.iterrows():
                    marketing_area_name = row['marketing_area'].strip()
                    area_id = area_name_to_id.get(marketing_area_name)
                    
                    if area_id and pd.notna(row['target_value']):
                        target = CoverageTarget(
                            area_id=area_id,
                            marketing_area=marketing_area_name,
                            business_line=row['business_line'],
                            target_value=int(row['target_value'])
                        )
                        db.merge(target)
                
                db.commit()
                logger.info(f"✅ Loaded coverage targets")
                
        except Exception as e:
            logger.error(f"❌ Failed to load coverage targets: {e}")
    
    def migrate_from_old_system(self, force_refresh=False):
        """Migrate data from the old in-memory system"""
        logger.info("Migrating data from old system...")
        
        try:
            pipeline = OptimizedDataPipeline()
            
            if force_refresh:
                logger.info("Force refresh enabled - fetching fresh data from Metabase...")
                # This will fetch fresh data and populate the database
                import asyncio
                result = asyncio.run(pipeline.refresh_all_data())
                logger.info(f"✅ Data migration completed: {result}")
            else:
                logger.info("Using cached data migration (if available)")
                # Implement logic to use existing CSV files or cached data
                self._migrate_from_files()
                
        except Exception as e:
            logger.error(f"❌ Data migration failed: {e}")
            raise
    
    def _migrate_from_files(self):
        """Migrate from existing CSV files if available"""
        # Implementation for migrating from CSV files
        # This is a placeholder - adapt based on your existing data files
        logger.info("Migrating from existing data files...")
        
        # Look for existing CSV exports
        data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        
        # Check for orders data
        orders_file = os.path.join(data_dir, 'orders_export.csv')
        if os.path.exists(orders_file):
            self._load_orders_from_csv(orders_file)
        
        # Check for vendors data
        vendors_file = os.path.join(data_dir, 'vendors_export.csv')
        if os.path.exists(vendors_file):
            self._load_vendors_from_csv(vendors_file)
    
    def _load_orders_from_csv(self, file_path):
        """Load orders from CSV file"""
        logger.info(f"Loading orders from {file_path}...")
        
        try:
            df = pd.read_csv(file_path)
            
            with Session(self.engine) as db:
                # Process in chunks for memory efficiency
                chunk_size = 10000
                for i in range(0, len(df), chunk_size):
                    chunk = df.iloc[i:i + chunk_size]
                    orders = []
                    
                    for _, row in chunk.iterrows():
                        order = Order(
                            order_id=row['order_id'],
                            vendor_code=row['vendor_code'],
                            customer_latitude=row.get('customer_latitude'),
                            customer_longitude=row.get('customer_longitude'),
                            business_line=row.get('business_line'),
                            marketing_area=row.get('marketing_area'),
                            city_id=row.get('city_id'),
                            city_name=row.get('city_name'),
                            organic=row.get('organic', False),
                            created_at=pd.to_datetime(row['created_at']) if 'created_at' in row else datetime.utcnow(),
                            user_id=row.get('user_id')
                        )
                        orders.append(order)
                    
                    db.bulk_save_objects(orders)
                    db.commit()
                    logger.info(f"Loaded {len(orders)} orders (chunk {i//chunk_size + 1})")
            
            logger.info(f"✅ Successfully loaded {len(df)} orders")
            
        except Exception as e:
            logger.error(f"❌ Failed to load orders from CSV: {e}")
            raise
    
    def _load_vendors_from_csv(self, file_path):
        """Load vendors from CSV file"""
        logger.info(f"Loading vendors from {file_path}...")
        
        try:
            df = pd.read_csv(file_path)
            
            with Session(self.engine) as db:
                vendors = []
                
                for _, row in df.iterrows():
                    vendor = Vendor(
                        vendor_code=row['vendor_code'],
                        vendor_name=row.get('vendor_name'),
                        latitude=row.get('latitude'),
                        longitude=row.get('longitude'),
                        radius=row.get('radius'),
                        original_radius=row.get('radius'),
                        status_id=row.get('status_id'),
                        visible=row.get('visible', True),
                        open=row.get('open', True),
                        grade=row.get('grade'),
                        business_line=row.get('business_line'),
                        city_id=row.get('city_id'),
                        city_name=row.get('city_name')
                    )
                    vendors.append(vendor)
                
                db.bulk_save_objects(vendors)
                db.commit()
            
            logger.info(f"✅ Successfully loaded {len(df)} vendors")
            
        except Exception as e:
            logger.error(f"❌ Failed to load vendors from CSV: {e}")
            raise
    
    def verify_installation(self):
        """Verify database installation and data integrity"""
        logger.info("Verifying database installation...")
        
        try:
            with Session(self.engine) as db:
                # Check table counts
                tables_info = {}
                
                tables_info['orders'] = db.query(Order).count()
                tables_info['vendors'] = db.query(Vendor).count()
                tables_info['marketing_areas'] = db.query(MarketingArea).count()
                tables_info['tehran_districts'] = db.query(TehranDistrict).count()
                tables_info['coverage_targets'] = db.query(CoverageTarget).count()
                
                logger.info("📊 Database Statistics:")
                for table, count in tables_info.items():
                    logger.info(f"  {table}: {count:,} records")
                
                # Verify data integrity
                self._verify_data_integrity(db)
                
                logger.info("✅ Database verification completed successfully")
                return tables_info
                
        except Exception as e:
            logger.error(f"❌ Database verification failed: {e}")
            raise
    
    def _verify_data_integrity(self, db):
        """Verify data integrity and constraints"""
        logger.info("Checking data integrity...")
        
        # Check for duplicate order IDs
        duplicate_orders = db.execute(text("""
            SELECT order_id, COUNT(*) as count 
            FROM orders 
            GROUP BY order_id 
            HAVING COUNT(*) > 1 
            LIMIT 5
        """)).fetchall()
        
        if duplicate_orders:
            logger.warning(f"Found {len(duplicate_orders)} duplicate order IDs")
        
        # Check for duplicate vendor codes
        duplicate_vendors = db.execute(text("""
            SELECT vendor_code, COUNT(*) as count 
            FROM vendors 
            GROUP BY vendor_code 
            HAVING COUNT(*) > 1 
            LIMIT 5
        """)).fetchall()
        
        if duplicate_vendors:
            logger.warning(f"Found {len(duplicate_vendors)} duplicate vendor codes")
        
        # Check for invalid coordinates
        invalid_coords = db.execute(text("""
            SELECT COUNT(*) as count 
            FROM orders 
            WHERE customer_latitude IS NOT NULL 
            AND customer_longitude IS NOT NULL 
            AND (customer_latitude < -90 OR customer_latitude > 90 
                 OR customer_longitude < -180 OR customer_longitude > 180)
        """)).fetchone()
        
        if invalid_coords.count > 0:
            logger.warning(f"Found {invalid_coords.count} orders with invalid coordinates")
        
        logger.info("✅ Data integrity check completed")

def main():
    parser = argparse.ArgumentParser(description='Initialize TapsiFood Dashboard Database')
    parser.add_argument('--create-tables', action='store_true', help='Create database tables')
    parser.add_argument('--drop-tables', action='store_true', help='Drop all tables (DANGER!)')
    parser.add_argument('--load-polygons', action='store_true', help='Load polygon data')
    parser.add_argument('--migrate-data', action='store_true', help='Migrate data from old system')
    parser.add_argument('--force-refresh', action='store_true', help='Force refresh data from Metabase')
    parser.add_argument('--create-indexes', action='store_true', help='Create additional indexes')
    parser.add_argument('--verify', action='store_true', help='Verify installation')
    parser.add_argument('--full-setup', action='store_true', help='Perform full setup')
    
    args = parser.parse_args()
    
    initializer = DatabaseInitializer()
    
    try:
        if args.full_setup:
            logger.info("🚀 Starting full database setup...")
            initializer.create_tables()
            initializer.create_indexes()
            initializer.load_polygon_data()
            initializer.migrate_from_old_system(args.force_refresh)
            initializer.verify_installation()
            logger.info("🎉 Full database setup completed successfully!")
        
        elif args.create_tables:
            initializer.create_tables()
        
        elif args.drop_tables:
            confirmation = input("Are you sure you want to drop all tables? Type 'yes' to confirm: ")
            if confirmation.lower() == 'yes':
                initializer.drop_tables()
            else:
                logger.info("Operation cancelled")
        
        elif args.load_polygons:
            initializer.load_polygon_data()
        
        elif args.migrate_data:
            initializer.migrate_from_old_system(args.force_refresh)
        
        elif args.create_indexes:
            initializer.create_indexes()
        
        elif args.verify:
            initializer.verify_installation()
        
        else:
            parser.print_help()
    
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()