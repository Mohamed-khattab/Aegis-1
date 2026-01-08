"""
Aegis-1 Main Application

FastAPI application entry point.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router as api_router
from api.websocket import websocket_router, set_websocket_output
from api import routes as routes_module
from core.orchestrator import CoreOrchestrator
from outputs.websocket_output import WebSocketOutput
from outputs.webhook import WebhookOutput
from outputs.email_output import EmailOutput
from outputs.database import DatabaseOutput
from outputs.message_queue import MessageQueueOutput
from db.redis_client import get_redis_client
from db.timescale import get_timescale_client
from config.settings import settings


# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


# Global instances
orchestrator: CoreOrchestrator = None
output_manager = None


class OutputManager:
    """Manages all output plugs."""
    
    def __init__(self):
        self._outputs: dict = {}
    
    async def initialize(self):
        """Initialize all output plugs."""
        # WebSocket output
        ws_output = WebSocketOutput()
        await ws_output.initialize()
        self._outputs["websocket"] = ws_output
        set_websocket_output(ws_output)
        
        # Database output
        db_output = DatabaseOutput()
        await db_output.initialize()
        self._outputs["database"] = db_output
        
        # Webhook output (if configured)
        if settings.webhook_url:
            webhook_output = WebhookOutput()
            await webhook_output.initialize()
            self._outputs["webhook"] = webhook_output
        
        # Email output (if configured)
        if settings.smtp_user and settings.smtp_password:
            email_output = EmailOutput()
            await email_output.initialize()
            self._outputs["email"] = email_output
        
        # Message queue output (if configured)
        if settings.rabbitmq_url:
            try:
                mq_output = MessageQueueOutput()
                await mq_output.initialize()
                self._outputs["message_queue"] = mq_output
            except Exception as e:
                logger.warning(f"Failed to initialize message queue: {e}")
        
        logger.info(f"Initialized {len(self._outputs)} output plugs")
    
    async def shutdown(self):
        """Shutdown all output plugs."""
        for output_id, output in self._outputs.items():
            try:
                await output.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down {output_id}: {e}")
    
    async def broadcast(self, signal):
        """Broadcast signal to all outputs."""
        tasks = []
        for output in self._outputs.values():
            tasks.append(output.deliver(signal))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for output_id, result in zip(self._outputs.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"Output {output_id} error: {result}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global orchestrator, output_manager
    
    logger.info("Starting Aegis-1...")
    
    # Initialize database connections
    redis = get_redis_client()
    await redis.connect()
    
    db = get_timescale_client()
    await db.connect()
    
    # Initialize orchestrator
    orchestrator = CoreOrchestrator()
    await orchestrator.initialize()
    
    # Inject into routes module
    routes_module._orchestrator = orchestrator
    
    # Initialize output manager
    output_manager = OutputManager()
    await output_manager.initialize()
    routes_module._output_manager = output_manager
    
    # Register signal callback to broadcast to outputs
    orchestrator.add_signal_callback(output_manager.broadcast)
    
    logger.info("Aegis-1 started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Aegis-1...")
    
    if orchestrator:
        await orchestrator.shutdown()
    
    if output_manager:
        await output_manager.shutdown()
    
    await redis.disconnect()
    await db.disconnect()
    
    logger.info("Aegis-1 shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Aegis-1 Trading System",
    description="Multi-Layer Agentic Trading System with Blackboard Architecture",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router, prefix="/api/v1")
app.include_router(websocket_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Aegis-1",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health")
async def health():
    """Quick health check endpoint."""
    return {"status": "healthy"}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.app_env == "development"
    )
