# models.py - SQLAlchemy Database Models
from sqlalchemy import Column, Integer, String, Boolean, DECIMAL, DateTime, Text, Index, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from geoalchemy2 import Geometry
import uuid

Base = declarative_base()

class Order(Base):
    """Orders table with optimized indexing"""
    __tablename__ = 'orders'
    
    id = Column(Integer, primary_key=True)
    order_id = Column(String(50), unique=True, nullable=False)
    vendor_code = Column(String(50), nullable=False)
    customer_latitude = Column(DECIMAL(10,8))
    customer_longitude = Column(DECIMAL(11,8))
    business_line = Column(String(50))
    marketing_area = Column(String(100))
    city_id = Column(Integer)
    city_name = Column(String(50))
    organic = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False)
    user_id = Column(String(50))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Define composite indexes for common queries
    __table_args__ = (
        Index('idx_orders_created_at', 'created_at'),
        Index('idx_orders_city_business', 'city_name', 'business_line'),
        Index('idx_orders_location', 'customer_latitude', 'customer_longitude'),
        Index('idx_orders_vendor_code', 'vendor_code'),
        Index('idx_orders_city_date', 'city_name', 'created_at'),
        Index('idx_orders_business_date', 'business_line', 'created_at'),
        Index('idx_orders_user_city', 'user_id', 'city_name'),
    )

class Vendor(Base):
    """Vendors table with spatial indexing"""
    __tablename__ = 'vendors'
    
    id = Column(Integer, primary_key=True)
    vendor_code = Column(String(50), unique=True, nullable=False)
    vendor_name = Column(String(200))
    latitude = Column(DECIMAL(10,8))
    longitude = Column(DECIMAL(11,8))
    radius = Column(DECIMAL(5,2))
    original_radius = Column(DECIMAL(5,2))
    status_id = Column(Integer)
    visible = Column(Boolean, default=True)
    open = Column(Boolean, default=True)
    grade = Column(String(10))
    business_line = Column(String(50))
    city_id = Column(Integer)
    city_name = Column(String(50))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Spatial column for advanced geospatial queries
    location = Column(Geometry('POINT', srid=4326))
    
    __table_args__ = (
        Index('idx_vendors_location', 'latitude', 'longitude'),
        Index('idx_vendors_city_status', 'city_name', 'status_id'),
        Index('idx_vendors_business_line', 'business_line'),
        Index('idx_vendors_grade', 'grade'),
        Index('idx_vendors_visibility', 'visible', 'open'),
        Index('idx_vendors_spatial', 'location', postgresql_using='gist'),
    )

class MarketingArea(Base):
    """Marketing areas with spatial geometry"""
    __tablename__ = 'marketing_areas'
    
    id = Column(Integer, primary_key=True)
    area_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    city_name = Column(String(50), nullable=False)
    geometry_wkt = Column(Text)
    geometry = Column(Geometry('POLYGON', srid=4326))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_marketing_areas_city', 'city_name'),
        Index('idx_marketing_areas_name', 'name'),
        Index('idx_marketing_areas_spatial', 'geometry', postgresql_using='gist'),
    )

class TehranDistrict(Base):
    """Tehran districts with population data"""
    __tablename__ = 'tehran_districts'
    
    id = Column(Integer, primary_key=True)
    district_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    district_type = Column(String(50))  # 'region' or 'main'
    population = Column(Integer)
    population_density = Column(DECIMAL(10,2))
    geometry_wkt = Column(Text)
    geometry = Column(Geometry('POLYGON', srid=4326))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_tehran_districts_type', 'district_type'),
        Index('idx_tehran_districts_name', 'name'),
        Index('idx_tehran_districts_spatial', 'geometry', postgresql_using='gist'),
    )

class CoverageTarget(Base):
    """Coverage targets for business analysis"""
    __tablename__ = 'coverage_targets'
    
    id = Column(Integer, primary_key=True)
    area_id = Column(String(50), nullable=False)
    marketing_area = Column(String(200), nullable=False)
    business_line = Column(String(50), nullable=False)
    target_value = Column(Integer, nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_coverage_targets_area_bl', 'area_id', 'business_line'),
        Index('idx_coverage_targets_marketing', 'marketing_area'),
    )

class DataRefreshLog(Base):
    """Track data refresh operations"""
    __tablename__ = 'data_refresh_logs'
    
    id = Column(Integer, primary_key=True)
    refresh_id = Column(String(50), default=lambda: str(uuid.uuid4()), unique=True)
    started_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime)
    status = Column(String(20))  # 'running', 'completed', 'failed'
    orders_processed = Column(Integer)
    vendors_processed = Column(Integer)
    error_message = Column(Text)
    duration_seconds = Column(Integer)
    
    __table_args__ = (
        Index('idx_refresh_logs_status', 'status'),
        Index('idx_refresh_logs_started', 'started_at'),
    )

class CacheMetrics(Base):
    """Cache performance metrics"""
    __tablename__ = 'cache_metrics'
    
    id = Column(Integer, primary_key=True)
    cache_key = Column(String(255), nullable=False)
    hit_count = Column(Integer, default=0)
    miss_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, default=func.now())
    cache_size_bytes = Column(Integer)
    expiry_time = Column(DateTime)
    
    __table_args__ = (
        Index('idx_cache_metrics_key', 'cache_key'),
        Index('idx_cache_metrics_accessed', 'last_accessed'),
    )

# Database connection configuration
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
import os

# Production database configuration
DATABASE_URL = os.getenv(
    'DATABASE_URL', 
    'postgresql://user:password@localhost:5432/tapsifood_dashboard'
)

# Optimized engine configuration for production
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,          # Number of connections to maintain
    max_overflow=30,       # Additional connections if needed
    pool_pre_ping=True,    # Validate connections before use
    pool_recycle=3600,     # Recycle connections every hour
    echo=False             # Set to True for SQL debugging
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """Database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    """Create all tables"""
    Base.metadata.create_all(bind=engine)

def drop_tables():
    """Drop all tables (use with caution!)"""
    Base.metadata.drop_all(bind=engine)