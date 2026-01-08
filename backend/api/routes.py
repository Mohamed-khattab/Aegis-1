"""
REST API Routes for Aegis-1

FastAPI endpoints for configuration, signals, and monitoring.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from models.signals import SignalAction


logger = logging.getLogger(__name__)

router = APIRouter()


# ===================
# Request/Response Models
# ===================

class PlugWeightUpdate(BaseModel):
    """Request to update plug weight."""
    weight: float = Field(..., ge=0.0, le=2.0, description="New weight (0.0-2.0)")


class PlugStatusUpdate(BaseModel):
    """Request to update plug status."""
    enabled: bool


class SignalQuery(BaseModel):
    """Query parameters for signals."""
    symbol: Optional[str] = None
    action: Optional[SignalAction] = None
    min_confidence: Optional[float] = Field(None, ge=0, le=1)
    hours: int = Field(24, ge=1, le=168)
    limit: int = Field(100, ge=1, le=1000)


class GenerateSignalRequest(BaseModel):
    """Request to generate a signal."""
    symbol: str
    include_news: bool = True
    include_historical: bool = True


class ConfigUpdate(BaseModel):
    """Request to update configuration."""
    key: str
    value: Any


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: str
    components: dict[str, bool]


class SignalResponse(BaseModel):
    """Signal response."""
    id: str
    timestamp: str
    action: str
    symbol: str
    confidence: float
    position_size: float
    reasoning: str
    risk_score: float
    risk_decision: str
    plug_contributions: dict[str, Any]


# ===================
# Dependency Injection
# ===================

# These will be injected by the main app
_orchestrator = None
_output_manager = None


def get_orchestrator():
    """Get orchestrator instance."""
    if _orchestrator is None:
        raise HTTPException(503, "Orchestrator not initialized")
    return _orchestrator


def get_output_manager():
    """Get output manager instance."""
    return _output_manager


# ===================
# Health & Status
# ===================

@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Check system health.
    
    Returns status of all system components.
    """
    orchestrator = get_orchestrator()
    health = await orchestrator.health_check()
    
    all_healthy = all(health.values())
    
    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        timestamp=datetime.utcnow().isoformat(),
        components=health
    )


@router.get("/status", tags=["Health"])
async def get_status():
    """
    Get detailed system status.
    
    Returns status of orchestrator, plugs, and outputs.
    """
    orchestrator = get_orchestrator()
    return await orchestrator.get_status()


# ===================
# Signals
# ===================

@router.post("/signals/generate", response_model=SignalResponse, tags=["Signals"])
async def generate_signal(request: GenerateSignalRequest):
    """
    Generate a trading signal for a symbol.
    
    Runs all plugs and returns consensus signal.
    """
    from models.market_data import MarketDataBundle
    
    orchestrator = get_orchestrator()
    
    # Create market data bundle (in production, this would be from feeds)
    market_data = MarketDataBundle(
        symbol=request.symbol,
        timestamp=datetime.utcnow()
    )
    
    # Generate signal
    signal = await orchestrator.generate_signal(request.symbol, market_data)
    
    return SignalResponse(
        id=str(signal.id),
        timestamp=signal.timestamp.isoformat(),
        action=signal.action.value,
        symbol=signal.symbol,
        confidence=signal.confidence,
        position_size=signal.position_size,
        reasoning=signal.reasoning,
        risk_score=signal.risk_score,
        risk_decision=signal.risk_decision.value,
        plug_contributions=signal.plug_contributions
    )


@router.get("/signals", tags=["Signals"])
async def list_signals(
    symbol: Optional[str] = None,
    action: Optional[str] = None,
    min_confidence: Optional[float] = Query(None, ge=0, le=1),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(100, ge=1, le=1000)
):
    """
    Query historical signals.
    
    Filter by symbol, action, confidence, and time range.
    """
    from db.timescale import get_timescale_client
    
    db = get_timescale_client()
    
    start_time = datetime.utcnow() - timedelta(hours=hours)
    signal_action = SignalAction(action) if action else None
    
    signals = await db.get_signals(
        symbol=symbol,
        action=signal_action,
        start_time=start_time,
        min_confidence=min_confidence,
        limit=limit
    )
    
    return [
        {
            "id": str(s.id),
            "timestamp": s.timestamp.isoformat(),
            "action": s.action.value,
            "symbol": s.symbol,
            "confidence": s.confidence,
            "risk_score": s.risk_score,
            "risk_decision": s.risk_decision.value
        }
        for s in signals
    ]


@router.get("/signals/{signal_id}", tags=["Signals"])
async def get_signal(signal_id: UUID):
    """Get a specific signal by ID."""
    from db.timescale import get_timescale_client
    
    db = get_timescale_client()
    signal = await db.get_signal(signal_id)
    
    if not signal:
        raise HTTPException(404, "Signal not found")
    
    return {
        "id": str(signal.id),
        "timestamp": signal.timestamp.isoformat(),
        "action": signal.action.value,
        "symbol": signal.symbol,
        "confidence": signal.confidence,
        "position_size": signal.position_size,
        "reasoning": signal.reasoning,
        "risk_score": signal.risk_score,
        "risk_decision": signal.risk_decision.value,
        "plug_contributions": signal.plug_contributions,
        "metadata": signal.metadata
    }


@router.get("/signals/stats/{symbol}", tags=["Signals"])
async def get_signal_stats(symbol: str, hours: int = Query(24, ge=1, le=168)):
    """Get signal statistics for a symbol."""
    from db.timescale import get_timescale_client
    
    db = get_timescale_client()
    return await db.get_signal_stats(symbol=symbol, hours=hours)


# ===================
# Plugs
# ===================

@router.get("/plugs", tags=["Plugs"])
async def list_plugs():
    """List all plugs with their status."""
    orchestrator = get_orchestrator()
    plugs = orchestrator.get_all_plugs()
    
    return {
        plug_id: plug.get_status()
        for plug_id, plug in plugs.items()
    }


@router.get("/plugs/{plug_id}", tags=["Plugs"])
async def get_plug(plug_id: str):
    """Get detailed status for a specific plug."""
    orchestrator = get_orchestrator()
    plug = orchestrator.get_plug(plug_id)
    
    if not plug:
        raise HTTPException(404, f"Plug '{plug_id}' not found")
    
    return plug.get_status()


@router.put("/plugs/{plug_id}/weight", tags=["Plugs"])
async def update_plug_weight(plug_id: str, update: PlugWeightUpdate):
    """Update the weight for a plug."""
    orchestrator = get_orchestrator()
    
    success = await orchestrator.set_plug_weight(plug_id, update.weight)
    
    if not success:
        raise HTTPException(404, f"Plug '{plug_id}' not found")
    
    return {"plug_id": plug_id, "weight": update.weight}


@router.put("/plugs/{plug_id}/status", tags=["Plugs"])
async def update_plug_status(plug_id: str, update: PlugStatusUpdate):
    """Enable or disable a plug."""
    orchestrator = get_orchestrator()
    
    if update.enabled:
        success = await orchestrator.enable_plug(plug_id)
    else:
        success = await orchestrator.disable_plug(plug_id)
    
    if not success:
        raise HTTPException(404, f"Plug '{plug_id}' not found")
    
    return {"plug_id": plug_id, "enabled": update.enabled}


@router.get("/plugs/performance", tags=["Plugs"])
async def get_plug_performance():
    """Get performance metrics for all plugs."""
    orchestrator = get_orchestrator()
    return orchestrator.dynamic_weighting.get_performance_summary()


@router.get("/plugs/ranking", tags=["Plugs"])
async def get_plug_ranking():
    """Get plugs ranked by performance."""
    orchestrator = get_orchestrator()
    ranking = orchestrator.dynamic_weighting.get_plug_ranking()
    
    return [
        {"plug_id": plug_id, "score": score}
        for plug_id, score in ranking
    ]


# ===================
# Configuration
# ===================

@router.get("/config", tags=["Configuration"])
async def get_config():
    """Get current system configuration."""
    from config.settings import settings
    
    return {
        "max_drawdown_percent": settings.max_drawdown_percent,
        "kill_switch_loss_percent": settings.kill_switch_loss_percent,
        "pinecone_similarity_threshold": settings.pinecone_similarity_threshold,
        "max_consensus_latency_ms": settings.max_consensus_latency_ms,
        "max_e2e_latency_ms": settings.max_e2e_latency_ms,
        "volatility_threshold_multiplier": settings.volatility_threshold_multiplier
    }


@router.get("/config/weights", tags=["Configuration"])
async def get_weights():
    """Get current plug weights."""
    orchestrator = get_orchestrator()
    return orchestrator.dynamic_weighting.get_all_weights()


@router.post("/config/weights/reset", tags=["Configuration"])
async def reset_weights():
    """Reset all plug weights to default."""
    orchestrator = get_orchestrator()
    orchestrator.dynamic_weighting.reset_all_weights()
    return {"message": "Weights reset to default"}


# ===================
# Risk
# ===================

@router.get("/risk/summary", tags=["Risk"])
async def get_risk_summary():
    """Get current risk summary."""
    orchestrator = get_orchestrator()
    risk_plug = orchestrator.get_plug("risk_analyst")
    
    if risk_plug:
        return risk_plug.get_risk_summary()
    
    return {"error": "Risk analyst plug not available"}


@router.post("/risk/session/reset", tags=["Risk"])
async def reset_risk_session():
    """Reset the risk session (e.g., at start of trading day)."""
    orchestrator = get_orchestrator()
    risk_plug = orchestrator.get_plug("risk_analyst")
    
    if risk_plug:
        risk_plug.reset_session()
        return {"message": "Risk session reset"}
    
    raise HTTPException(404, "Risk analyst plug not available")


# ===================
# Outputs
# ===================

@router.get("/outputs", tags=["Outputs"])
async def list_outputs():
    """List all output plugs with their status."""
    output_manager = get_output_manager()
    if not output_manager:
        return {}
    
    return {
        output_id: output.get_status()
        for output_id, output in output_manager._outputs.items()
    }


@router.put("/outputs/{output_id}/enable", tags=["Outputs"])
async def enable_output(output_id: str):
    """Enable an output plug."""
    output_manager = get_output_manager()
    if not output_manager:
        raise HTTPException(503, "Output manager not available")
    
    output = output_manager._outputs.get(output_id)
    if not output:
        raise HTTPException(404, f"Output '{output_id}' not found")
    
    output.enable()
    return {"output_id": output_id, "enabled": True}


@router.put("/outputs/{output_id}/disable", tags=["Outputs"])
async def disable_output(output_id: str):
    """Disable an output plug."""
    output_manager = get_output_manager()
    if not output_manager:
        raise HTTPException(503, "Output manager not available")
    
    output = output_manager._outputs.get(output_id)
    if not output:
        raise HTTPException(404, f"Output '{output_id}' not found")
    
    output.disable()
    return {"output_id": output_id, "enabled": False}
