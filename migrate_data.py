# scripts/migrate_data.py - Data Migration Utilities
import os
import sys
import pandas as pd
import pickle
import json
from datetime import datetime
import argparse
import logging
from pathlib import Path

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from models import engine, Order, Vendor
from sqlalchemy.orm import Session
from data_pipeline import OptimizedDataPipeline
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DataMigrator:
    """Handles migration from legacy system to production database"""
    
    def __init__(self):
        self.engine = engine
        self.pipeline = OptimizedDataPipeline()
        
    def export_from_memory(self, output_dir="exports"):
        """Export data from the old in-memory system (if still running)"""
        logger.info("Exporting data from legacy app.py system...")
        
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        # This would connect to your existing app.py if it's still running
        # and export the global variables to CSV files
        
        try:
            # Import your existing app to get the global data
            # Note: This requires your original app.py to be available
            logger.warning("This function requires your original app.py to be running")
            logger.info("Please use export_from_csv() if you have CSV files instead")
            
            # Example implementation:
            # from app import df_orders, df_vendors, gdf_marketing_areas
            # 
            # # Export orders
            # if df_orders is not None:
            #     orders_file = output_path / f"orders_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            #     df_orders.to_csv(orders_file, index=False)
            #     logger.info(f"Exported {len(df_orders)} orders to {orders_file}")
            # 
            # # Export vendors
            # if df_vendors is not None:
            #     vendors_file = output_path / f"vendors_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            #     df_vendors.to_csv(vendors_file, index=False)
            #     logger.info(f"Exported {len(df_vendors)} vendors to {vendors_file}")
            
        except ImportError as e:
            logger.error(f"Could not import legacy app.py: {e}")
            logger.info("Please export your data manually or use the CSV migration method")
    
    def export_from_csv(self, csv_dir="data/exports", output_dir="migration_exports"):
        """Export existing CSV files to standardized format"""
        logger.info(f"Exporting CSV files from {csv_dir}...")
        
        csv_path = Path(csv_dir)
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        if not csv_path.exists():
            logger.warning(f"CSV directory {csv_dir} does not exist")
            return
        
        # Look for existing CSV files
        csv_files = list(csv_path.glob("*.csv"))
        
        if not csv_files:
            logger.warning(f"No CSV files found in {csv_dir}")
            return
        
        for csv_file in csv_files:
            try:
                # Read and process CSV
                df = pd.read_csv(csv_file)
                
                # Determine file type based on columns
                if self._is_orders_file(df):
                    output_file = output_path / f"orders_migrated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                    processed_df = self._process_orders_for_migration(df)
                elif self._is_vendors_file(df):
                    output_file = output_path / f"vendors_migrated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                    processed_df = self._process_vendors_for_migration(df)
                else:
                    logger.warning(f"Unknown CSV format: {csv_file}")
                    continue
                
                # Save processed file
                processed_df.to_csv(output_file, index=False)
                logger.info(f"Migrated {csv_file.name} -> {output_file.name} ({len(processed_df)} rows)")
                
            except Exception as e:
                logger.error(f"Error processing {csv_file}: {e}")
    
    def _is_orders_file(self, df):
        """Detect if CSV is an orders file"""
        orders_columns = ['order_id', 'vendor_code', 'customer_latitude', 'customer_longitude']
        return all(col in df.columns for col in orders_columns)
    
    def _is_vendors_file(self, df):
        """Detect if CSV is a vendors file"""
        vendors_columns = ['vendor_code', 'latitude', 'longitude']
        return all(col in df.columns for col in vendors_columns)
    
    def _process_orders_for_migration(self, df):
        """Process orders data for database compatibility"""
        # Ensure required columns exist
        required_cols = {
            'order_id': 'string',
            'vendor_code': 'string',
            'customer_latitude': 'float64',
            'customer_longitude': 'float64',
            'business_line': 'string',
            'marketing_area': 'string',
            'city_id': 'Int64',
            'city_name': 'string',
            'organic': 'boolean',
            'created_at': 'datetime64[ns]',
            'user_id': 'string'
        }
        
        # Add missing columns with defaults
        for col, dtype in required_cols.items():
            if col not in df.columns:
                if dtype == 'string':
                    df[col] = None
                elif dtype == 'Int64':
                    df[col] = pd.NA
                elif dtype == 'float64':
                    df[col] = pd.NA
                elif dtype == 'boolean':
                    df[col] = False
                elif dtype == 'datetime64[ns]':
                    df[col] = datetime.now()
        
        # Data type conversions
        if 'created_at' in df.columns:
            df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce')
        
        if 'organic' in df.columns:
            df['organic'] = df['organic'].fillna(False).astype(bool)
        
        # City name mapping
        city_map = {1: "mashhad", 2: "tehran", 5: "shiraz"}
        if 'city_id' in df.columns and 'city_name' not in df.columns:
            df['city_name'] = df['city_id'].map(city_map)
        
        return df
    
    def _process_vendors_for_migration(self, df):
        """Process vendors data for database compatibility"""
        required_cols = {
            'vendor_code': 'string',
            'vendor_name': 'string',
            'latitude': 'float64',
            'longitude': 'float64',
            'radius': 'float64',
            'original_radius': 'float64',
            'status_id': 'Int64',
            'visible': 'boolean',
            'open': 'boolean',
            'grade': 'string',
            'business_line': 'string',
            'city_id': 'Int64',
            'city_name': 'string'
        }
        
        # Add missing columns with defaults
        for col, dtype in required_cols.items():
            if col not in df.columns:
                if dtype == 'string':
                    df[col] = None
                elif dtype == 'Int64':
                    df[col] = pd.NA
                elif dtype == 'float64':
                    df[col] = pd.NA
                elif dtype == 'boolean':
                    df[col] = True
        
        # Copy radius to original_radius if not exists
        if 'radius' in df.columns and 'original_radius' not in df.columns:
            df['original_radius'] = df['radius']
        
        # City name mapping
        city_map = {1: "mashhad", 2: "tehran", 5: "shiraz"}
        if 'city_id' in df.columns:
            df['city_name'] = df['city_id'].map(city_map)
        
        return df
    
    async def migrate_from_metabase(self):
        """Fresh migration directly from Metabase"""
        logger.info("Starting fresh migration from Metabase...")
        
        try:
            result = await self.pipeline.refresh_all_data()
            logger.info(f"Migration completed: {result}")
            return result
        except Exception as e:
            logger.error(f"Metabase migration failed: {e}")
            raise
    
    def migrate_from_files(self, files_dir="migration_exports"):
        """Migrate processed CSV files to database"""
        logger.info(f"Migrating from files in {files_dir}...")
        
        files_path = Path(files_dir)
        if not files_path.exists():
            logger.error(f"Migration directory {files_dir} does not exist")
            return
        
        # Find migration files
        orders_files = list(files_path.glob("orders_migrated_*.csv"))
        vendors_files = list(files_path.glob("vendors_migrated_*.csv"))
        
        if not orders_files and not vendors_files:
            logger.warning("No migration files found")
            return
        
        with Session(self.engine) as db:
            # Migrate orders
            for orders_file in orders_files:
                logger.info(f"Migrating orders from {orders_file}")
                self._migrate_orders_file(db, orders_file)
            
            # Migrate vendors
            for vendors_file in vendors_files:
                logger.info(f"Migrating vendors from {vendors_file}")
                self._migrate_vendors_file(db, vendors_file)
    
    def _migrate_orders_file(self, db: Session, file_path: Path):
        """Migrate single orders file"""
        try:
            df = pd.read_csv(file_path)
            
            # Process in chunks for memory efficiency
            chunk_size = 10000
            total_processed = 0
            
            for i in range(0, len(df), chunk_size):
                chunk = df.iloc[i:i + chunk_size]
                orders = []
                
                for _, row in chunk.iterrows():
                    order = Order(
                        order_id=str(row.get('order_id', '')),
                        vendor_code=str(row.get('vendor_code', '')),
                        customer_latitude=row.get('customer_latitude'),
                        customer_longitude=row.get('customer_longitude'),
                        business_line=str(row.get('business_line', '')) if pd.notna(row.get('business_line')) else None,
                        marketing_area=str(row.get('marketing_area', '')) if pd.notna(row.get('marketing_area')) else None,
                        city_id=row.get('city_id'),
                        city_name=str(row.get('city_name', '')) if pd.notna(row.get('city_name')) else None,
                        organic=bool(row.get('organic', False)),
                        created_at=pd.to_datetime(row.get('created_at')) if pd.notna(row.get('created_at')) else datetime.now(),
                        user_id=str(row.get('user_id', '')) if pd.notna(row.get('user_id')) else None
                    )
                    orders.append(order)
                
                # Bulk insert
                db.bulk_save_objects(orders)
                db.commit()
                total_processed += len(orders)
                
                logger.info(f"Processed {total_processed}/{len(df)} orders...")
            
            logger.info(f"✅ Migrated {total_processed} orders from {file_path.name}")
            
        except Exception as e:
            logger.error(f"Error migrating orders file {file_path}: {e}")
            db.rollback()
    
    def _migrate_vendors_file(self, db: Session, file_path: Path):
        """Migrate single vendors file"""
        try:
            df = pd.read_csv(file_path)
            vendors = []
            
            for _, row in df.iterrows():
                vendor = Vendor(
                    vendor_code=str(row.get('vendor_code', '')),
                    vendor_name=str(row.get('vendor_name', '')) if pd.notna(row.get('vendor_name')) else None,
                    latitude=row.get('latitude'),
                    longitude=row.get('longitude'),
                    radius=row.get('radius'),
                    original_radius=row.get('original_radius', row.get('radius')),
                    status_id=row.get('status_id'),
                    visible=bool(row.get('visible', True)),
                    open=bool(row.get('open', True)),
                    grade=str(row.get('grade', '')) if pd.notna(row.get('grade')) else None,
                    business_line=str(row.get('business_line', '')) if pd.notna(row.get('business_line')) else None,
                    city_id=row.get('city_id'),
                    city_name=str(row.get('city_name', '')) if pd.notna(row.get('city_name')) else None
                )
                vendors.append(vendor)
            
            # Bulk insert
            db.bulk_save_objects(vendors)
            db.commit()
            
            logger.info(f"✅ Migrated {len(vendors)} vendors from {file_path.name}")
            
        except Exception as e:
            logger.error(f"Error migrating vendors file {file_path}: {e}")
            db.rollback()
    
    def create_backup(self, backup_dir="backups"):
        """Create backup of current database"""
        logger.info("Creating database backup...")
        
        backup_path = Path(backup_dir)
        backup_path.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        with Session(self.engine) as db:
            # Backup orders
            orders = db.query(Order).all()
            if orders:
                orders_df = pd.DataFrame([{
                    'order_id': o.order_id,
                    'vendor_code': o.vendor_code,
                    'customer_latitude': o.customer_latitude,
                    'customer_longitude': o.customer_longitude,
                    'business_line': o.business_line,
                    'marketing_area': o.marketing_area,
                    'city_id': o.city_id,
                    'city_name': o.city_name,
                    'organic': o.organic,
                    'created_at': o.created_at,
                    'user_id': o.user_id
                } for o in orders])
                
                orders_backup = backup_path / f"orders_backup_{timestamp}.csv"
                orders_df.to_csv(orders_backup, index=False)
                logger.info(f"Backed up {len(orders)} orders to {orders_backup}")
            
            # Backup vendors
            vendors = db.query(Vendor).all()
            if vendors:
                vendors_df = pd.DataFrame([{
                    'vendor_code': v.vendor_code,
                    'vendor_name': v.vendor_name,
                    'latitude': v.latitude,
                    'longitude': v.longitude,
                    'radius': v.radius,
                    'original_radius': v.original_radius,
                    'status_id': v.status_id,
                    'visible': v.visible,
                    'open': v.open,
                    'grade': v.grade,
                    'business_line': v.business_line,
                    'city_id': v.city_id,
                    'city_name': v.city_name
                } for v in vendors])
                
                vendors_backup = backup_path / f"vendors_backup_{timestamp}.csv"
                vendors_df.to_csv(vendors_backup, index=False)
                logger.info(f"Backed up {len(vendors)} vendors to {vendors_backup}")

def main():
    parser = argparse.ArgumentParser(description='TapsiFood Dashboard Data Migration')
    parser.add_argument('--export-memory', action='store_true', help='Export from legacy app.py memory')
    parser.add_argument('--export-csv', action='store_true', help='Export from existing CSV files')
    parser.add_argument('--migrate-metabase', action='store_true', help='Fresh migration from Metabase')
    parser.add_argument('--migrate-files', action='store_true', help='Migrate from processed CSV files')
    parser.add_argument('--backup', action='store_true', help='Create database backup')
    parser.add_argument('--csv-dir', default='data/exports', help='Directory with existing CSV files')
    parser.add_argument('--output-dir', default='migration_exports', help='Output directory for processed files')
    parser.add_argument('--files-dir', default='migration_exports', help='Directory with migration files')
    
    args = parser.parse_args()
    
    migrator = DataMigrator()
    
    try:
        if args.export_memory:
            migrator.export_from_memory(args.output_dir)
        
        elif args.export_csv:
            migrator.export_from_csv(args.csv_dir, args.output_dir)
        
        elif args.migrate_metabase:
            logger.info("Starting fresh Metabase migration...")
            asyncio.run(migrator.migrate_from_metabase())
        
        elif args.migrate_files:
            migrator.migrate_from_files(args.files_dir)
        
        elif args.backup:
            migrator.create_backup()
        
        else:
            parser.print_help()
    
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()