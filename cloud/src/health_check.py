"""AutoReels Pro v10 — Health Check Endpoints"""

from flask import Blueprint, jsonify
from sqlalchemy import text
from datetime import datetime
import os

health_bp = Blueprint('health', __name__)

@health_bp.route('/health', methods=['GET'])
def health_check():
    """Liveness probe - is app running"""
    return jsonify({'status': 'alive', 'timestamp': datetime.utcnow().isoformat()}), 200

@health_bp.route('/ready', methods=['GET'])
def readiness_check():
    """Readiness probe - can handle requests"""
    try:
        # Check database
        from src.database.schema import Base
        from sqlalchemy import create_engine
        db_url = os.getenv('DATABASE_URL', 'sqlite:///autoreels.db')
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        
        # Check Redis
        import redis
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
        r = redis.from_url(redis_url)
        r.ping()
        
        return jsonify({
            'status': 'ready',
            'database': 'connected',
            'redis': 'connected',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'not_ready',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 503

@health_bp.route('/metrics', methods=['GET'])
def metrics():
    """Prometheus-format metrics"""
    try:
        from src.database.schema import Video, Upload, PostMetric
        from sqlalchemy import create_engine, func
        from sqlalchemy.orm import sessionmaker
        
        db_url = os.getenv('DATABASE_URL', 'sqlite:///autoreels.db')
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Collect metrics
        total_videos = session.query(Video).count()
        processed_videos = session.query(Video).filter(Video.status == 'done').count()
        total_uploads = session.query(Upload).count()
        total_metrics = session.query(PostMetric).count()
        
        avg_engagement = session.query(func.avg(PostMetric.views)).scalar() or 0
        
        metrics_text = f"""# HELP autoreels_videos_total Total videos processed
# TYPE autoreels_videos_total counter
autoreels_videos_total {total_videos}

# HELP autoreels_videos_processed Successfully processed videos
# TYPE autoreels_videos_processed counter
autoreels_videos_processed {processed_videos}

# HELP autoreels_uploads_total Total platform uploads
# TYPE autoreels_uploads_total counter
autoreels_uploads_total {total_uploads}

# HELP autoreels_metrics_total Total engagement metrics collected
# TYPE autoreels_metrics_total counter
autoreels_metrics_total {total_metrics}

# HELP autoreels_avg_views Average views per upload
# TYPE autoreels_avg_views gauge
autoreels_avg_views {avg_engagement}
"""
        
        return metrics_text, 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        return f"Error collecting metrics: {e}", 503

@health_bp.route('/status', methods=['GET'])
def status():
    """Detailed status information"""
    try:
        from src.database.schema import Video, Upload, Account
        from sqlalchemy import create_engine, func
        from sqlalchemy.orm import sessionmaker
        import redis
        
        db_url = os.getenv('DATABASE_URL', 'sqlite:///autoreels.db')
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Database stats
        videos = {
            'total': session.query(Video).count(),
            'processing': session.query(Video).filter(Video.status == 'processing').count(),
            'done': session.query(Video).filter(Video.status == 'done').count(),
            'failed': session.query(Video).filter(Video.status == 'failed').count(),
        }
        
        uploads = {
            'total': session.query(Upload).count(),
            'live': session.query(Upload).filter(Upload.status == 'live').count(),
            'failed': session.query(Upload).filter(Upload.status == 'failed').count(),
        }
        
        accounts = {
            'total': session.query(Account).count(),
            'active': session.query(Account).filter(Account.status == 'active').count(),
            'circuit_breaker_open': session.query(Account).filter(Account.circuit_breaker_open == True).count(),
        }
        
        # Redis stats
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
        r = redis.from_url(redis_url)
        redis_info = r.info()
        
        return jsonify({
            'status': 'operational',
            'timestamp': datetime.utcnow().isoformat(),
            'videos': videos,
            'uploads': uploads,
            'accounts': accounts,
            'redis': {
                'connected_clients': redis_info.get('connected_clients', 0),
                'used_memory_human': redis_info.get('used_memory_human', '0B'),
                'uptime_seconds': redis_info.get('uptime_in_seconds', 0),
            }
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 503
