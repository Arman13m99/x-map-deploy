# cache_manager.py - Advanced Redis Caching System
import redis
import aioredis
import json
import pickle
import pandas as pd
import numpy as np
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Dict, List
import hashlib
import gzip
import zlib

logger = logging.getLogger(__name__)

class CacheManager:
    """Advanced Redis cache manager with async support and intelligent compression"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis_client = redis.from_url(redis_url, decode_responses=False)
        self._aio_redis = None
        self.compression_threshold = 1024  # Compress data larger than 1KB
        
    async def get_aio_redis(self):
        """Get async Redis client (singleton)"""
        if self._aio_redis is None:
            self._aio_redis = await aioredis.from_url(self.redis_url)
        return self._aio_redis
    
    def _compress_data(self, data: bytes) -> bytes:
        """Compress data if it's larger than threshold"""
        if len(data) > self.compression_threshold:
            compressed = zlib.compress(data)
            # Only use compression if it actually reduces size
            if len(compressed) < len(data):
                return b'COMPRESSED:' + compressed
        return data
    
    def _decompress_data(self, data: bytes) -> bytes:
        """Decompress data if it was compressed"""
        if data.startswith(b'COMPRESSED:'):
            return zlib.decompress(data[11:])  # Remove 'COMPRESSED:' prefix
        return data
    
    def _serialize_dataframe(self, df: pd.DataFrame) -> bytes:
        """Efficient DataFrame serialization"""
        # Use pickle for DataFrames as it's more efficient than JSON
        return pickle.dumps(df, protocol=pickle.HIGHEST_PROTOCOL)
    
    def _deserialize_dataframe(self, data: bytes) -> pd.DataFrame:
        """Efficient DataFrame deserialization"""
        return pickle.loads(data)
    
    def _create_cache_key(self, prefix: str, **kwargs) -> str:
        """Create consistent cache key from parameters"""
        key_data = {k: v for k, v in sorted(kwargs.items()) if v is not None}
        key_hash = hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
        return f"{prefix}:{key_hash}"
    
    # Synchronous methods
    def cache_dataframe(self, key: str, df: pd.DataFrame, expiry_hours: int = 24) -> bool:
        """Cache pandas DataFrame with compression"""
        try:
            data = self._serialize_dataframe(df)
            compressed_data = self._compress_data(data)
            
            success = self.redis_client.setex(
                key, 
                timedelta(hours=expiry_hours), 
                compressed_data
            )
            
            if success:
                # Store metadata
                metadata = {
                    'rows': len(df),
                    'columns': len(df.columns),
                    'size_bytes': len(compressed_data),
                    'cached_at': datetime.utcnow().isoformat(),
                    'expiry_hours': expiry_hours
                }
                self.redis_client.setex(
                    f"{key}:meta",
                    timedelta(hours=expiry_hours + 1),  # Keep metadata slightly longer
                    json.dumps(metadata)
                )
                
                logger.info(f"Cached DataFrame {key}: {len(df)} rows, {len(compressed_data)} bytes")
            
            return success
        except Exception as e:
            logger.error(f"Failed to cache DataFrame {key}: {e}")
            return False
    
    def get_dataframe(self, key: str) -> Optional[pd.DataFrame]:
        """Retrieve cached DataFrame"""
        try:
            data = self.redis_client.get(key)
            if data:
                decompressed_data = self._decompress_data(data)
                df = self._deserialize_dataframe(decompressed_data)
                logger.debug(f"Cache hit for DataFrame {key}: {len(df)} rows")
                return df
            else:
                logger.debug(f"Cache miss for DataFrame {key}")
                return None
        except Exception as e:
            logger.error(f"Failed to retrieve DataFrame {key}: {e}")
            return None
    
    def cache_json(self, key: str, data: Any, expiry_hours: int = 24) -> bool:
        """Cache JSON-serializable data"""
        try:
            json_data = json.dumps(data, default=str).encode('utf-8')
            compressed_data = self._compress_data(json_data)
            
            success = self.redis_client.setex(
                key,
                timedelta(hours=expiry_hours),
                compressed_data
            )
            
            if success:
                logger.debug(f"Cached JSON {key}: {len(compressed_data)} bytes")
            
            return success
        except Exception as e:
            logger.error(f"Failed to cache JSON {key}: {e}")
            return False
    
    def get_json(self, key: str) -> Optional[Any]:
        """Retrieve cached JSON data"""
        try:
            data = self.redis_client.get(key)
            if data:
                decompressed_data = self._decompress_data(data)
                result = json.loads(decompressed_data.decode('utf-8'))
                logger.debug(f"Cache hit for JSON {key}")
                return result
            else:
                logger.debug(f"Cache miss for JSON {key}")
                return None
        except Exception as e:
            logger.error(f"Failed to retrieve JSON {key}: {e}")
            return None
    
    def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching pattern"""
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                deleted = self.redis_client.delete(*keys)
                logger.info(f"Invalidated {deleted} keys matching pattern: {pattern}")
                return deleted
            return 0
        except Exception as e:
            logger.error(f"Failed to invalidate pattern {pattern}: {e}")
            return 0
    
    def get_cache_info(self, key: str) -> Optional[Dict]:
        """Get cache metadata information"""
        try:
            meta_data = self.redis_client.get(f"{key}:meta")
            if meta_data:
                return json.loads(meta_data)
            return None
        except Exception as e:
            logger.error(f"Failed to get cache info for {key}: {e}")
            return None
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get overall cache statistics"""
        try:
            info = self.redis_client.info()
            return {
                'used_memory': info.get('used_memory_human', 'Unknown'),
                'connected_clients': info.get('connected_clients', 0),
                'total_commands_processed': info.get('total_commands_processed', 0),
                'cache_hit_rate': self._calculate_hit_rate(),
                'key_count': self.redis_client.dbsize()
            }
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {}
    
    def _calculate_hit_rate(self) -> float:
        """Calculate cache hit rate"""
        try:
            info = self.redis_client.info()
            hits = info.get('keyspace_hits', 0)
            misses = info.get('keyspace_misses', 0)
            total = hits + misses
            return (hits / total * 100) if total > 0 else 0.0
        except:
            return 0.0
    
    # Async methods
    async def cache_dataframe_async(self, key: str, df: pd.DataFrame, expiry_hours: int = 24) -> bool:
        """Async cache DataFrame"""
        try:
            redis_client = await self.get_aio_redis()
            
            data = self._serialize_dataframe(df)
            compressed_data = self._compress_data(data)
            
            success = await redis_client.setex(
                key,
                int(timedelta(hours=expiry_hours).total_seconds()),
                compressed_data
            )
            
            if success:
                metadata = {
                    'rows': len(df),
                    'columns': len(df.columns),
                    'size_bytes': len(compressed_data),
                    'cached_at': datetime.utcnow().isoformat(),
                    'expiry_hours': expiry_hours
                }
                await redis_client.setex(
                    f"{key}:meta",
                    int(timedelta(hours=expiry_hours + 1).total_seconds()),
                    json.dumps(metadata)
                )
                
                logger.info(f"Async cached DataFrame {key}: {len(df)} rows, {len(compressed_data)} bytes")
            
            return success
        except Exception as e:
            logger.error(f"Failed to async cache DataFrame {key}: {e}")
            return False
    
    async def get_dataframe_async(self, key: str) -> Optional[pd.DataFrame]:
        """Async retrieve DataFrame"""
        try:
            redis_client = await self.get_aio_redis()
            
            data = await redis_client.get(key)
            if data:
                decompressed_data = self._decompress_data(data)
                df = self._deserialize_dataframe(decompressed_data)
                logger.debug(f"Async cache hit for DataFrame {key}: {len(df)} rows")
                return df
            else:
                logger.debug(f"Async cache miss for DataFrame {key}")
                return None
        except Exception as e:
            logger.error(f"Failed to async retrieve DataFrame {key}: {e}")
            return None
    
    async def cache_json_async(self, key: str, data: Any, expiry_hours: int = 24) -> bool:
        """Async cache JSON data"""
        try:
            redis_client = await self.get_aio_redis()
            
            json_data = json.dumps(data, default=str).encode('utf-8')
            compressed_data = self._compress_data(json_data)
            
            success = await redis_client.setex(
                key,
                int(timedelta(hours=expiry_hours).total_seconds()),
                compressed_data
            )
            
            if success:
                logger.debug(f"Async cached JSON {key}: {len(compressed_data)} bytes")
            
            return success
        except Exception as e:
            logger.error(f"Failed to async cache JSON {key}: {e}")
            return False
    
    async def get_json_async(self, key: str) -> Optional[Any]:
        """Async retrieve JSON data"""
        try:
            redis_client = await self.get_aio_redis()
            
            data = await redis_client.get(key)
            if data:
                decompressed_data = self._decompress_data(data)
                result = json.loads(decompressed_data.decode('utf-8'))
                logger.debug(f"Async cache hit for JSON {key}")
                return result
            else:
                logger.debug(f"Async cache miss for JSON {key}")
                return None
        except Exception as e:
            logger.error(f"Failed to async retrieve JSON {key}: {e}")
            return None
    
    async def invalidate_pattern_async(self, pattern: str) -> int:
        """Async invalidate keys matching pattern"""
        try:
            redis_client = await self.get_aio_redis()
            
            # Get keys matching pattern
            keys = []
            async for key in redis_client.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                deleted = await redis_client.delete(*keys)
                logger.info(f"Async invalidated {deleted} keys matching pattern: {pattern}")
                return deleted
            return 0
        except Exception as e:
            logger.error(f"Failed to async invalidate pattern {pattern}: {e}")
            return 0
    
    # Smart caching methods
    def cache_query_result(self, query_params: Dict, result: Any, expiry_hours: int = 1) -> str:
        """Cache query result with auto-generated key"""
        cache_key = self._create_cache_key("query", **query_params)
        
        if isinstance(result, pd.DataFrame):
            self.cache_dataframe(cache_key, result, expiry_hours)
        else:
            self.cache_json(cache_key, result, expiry_hours)
        
        return cache_key
    
    def get_query_result(self, query_params: Dict) -> Optional[Any]:
        """Get cached query result"""
        cache_key = self._create_cache_key("query", **query_params)
        
        # Try DataFrame first
        result = self.get_dataframe(cache_key)
        if result is not None:
            return result
        
        # Try JSON
        return self.get_json(cache_key)
    
    async def cache_query_result_async(self, query_params: Dict, result: Any, expiry_hours: int = 1) -> str:
        """Async cache query result"""
        cache_key = self._create_cache_key("query", **query_params)
        
        if isinstance(result, pd.DataFrame):
            await self.cache_dataframe_async(cache_key, result, expiry_hours)
        else:
            await self.cache_json_async(cache_key, result, expiry_hours)
        
        return cache_key
    
    async def get_query_result_async(self, query_params: Dict) -> Optional[Any]:
        """Async get cached query result"""
        cache_key = self._create_cache_key("query", **query_params)
        
        # Try DataFrame first
        result = await self.get_dataframe_async(cache_key)
        if result is not None:
            return result
        
        # Try JSON
        return await self.get_json_async(cache_key)
    
    def warm_cache(self, keys_and_data: List[tuple]) -> int:
        """Warm cache with multiple key-value pairs"""
        success_count = 0
        
        for key, data, expiry_hours in keys_and_data:
            try:
                if isinstance(data, pd.DataFrame):
                    if self.cache_dataframe(key, data, expiry_hours):
                        success_count += 1
                else:
                    if self.cache_json(key, data, expiry_hours):
                        success_count += 1
            except Exception as e:
                logger.error(f"Failed to warm cache for key {key}: {e}")
        
        logger.info(f"Cache warming completed: {success_count} successful caches")
        return success_count
    
    async def close(self):
        """Close async Redis connection"""
        if self._aio_redis:
            await self._aio_redis.close()

# Global cache instance
cache_manager = CacheManager()