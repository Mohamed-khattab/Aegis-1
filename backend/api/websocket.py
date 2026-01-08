"""
WebSocket API for Aegis-1

Real-time signal streaming to dashboard clients.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from outputs.websocket_output import WebSocketOutput


logger = logging.getLogger(__name__)

websocket_router = APIRouter()

# Global WebSocket output instance
_ws_output: Optional[WebSocketOutput] = None


def set_websocket_output(ws_output: WebSocketOutput) -> None:
    """Set the WebSocket output instance."""
    global _ws_output
    _ws_output = ws_output


def get_websocket_output() -> Optional[WebSocketOutput]:
    """Get the WebSocket output instance."""
    return _ws_output


@websocket_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint for signal streaming.
    
    Clients connect here to receive real-time signals and system updates.
    """
    await websocket.accept()
    
    ws_output = get_websocket_output()
    if ws_output:
        await ws_output.register(websocket)
    
    # Send welcome message
    await websocket.send_json({
        "type": "connected",
        "data": {
            "message": "Connected to Aegis-1 signal stream",
            "timestamp": datetime.utcnow().isoformat()
        }
    })
    
    try:
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Receive messages from client (for commands/subscriptions)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0  # Ping every 60 seconds
                )
                
                # Handle client messages
                await handle_client_message(websocket, data)
                
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if ws_output:
            await ws_output.unregister(websocket)


async def handle_client_message(websocket: WebSocket, data: str) -> None:
    """
    Handle messages from WebSocket clients.
    
    Supported message types:
    - subscribe: Subscribe to specific symbols
    - unsubscribe: Unsubscribe from symbols
    - pong: Response to ping
    - get_status: Request current status
    """
    try:
        message = json.loads(data)
        msg_type = message.get("type", "")
        
        if msg_type == "pong":
            # Client responding to ping
            pass
            
        elif msg_type == "subscribe":
            # Subscribe to specific symbols
            symbols = message.get("symbols", [])
            await websocket.send_json({
                "type": "subscribed",
                "data": {"symbols": symbols}
            })
            
        elif msg_type == "unsubscribe":
            # Unsubscribe from symbols
            symbols = message.get("symbols", [])
            await websocket.send_json({
                "type": "unsubscribed",
                "data": {"symbols": symbols}
            })
            
        elif msg_type == "get_status":
            # Send current system status
            # Import here to avoid circular imports
            from api.routes import get_orchestrator
            try:
                orchestrator = get_orchestrator()
                status = await orchestrator.get_status()
                await websocket.send_json({
                    "type": "status",
                    "data": status
                })
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": str(e)}
                })
                
        elif msg_type == "get_health":
            # Send health check
            from api.routes import get_orchestrator
            try:
                orchestrator = get_orchestrator()
                health = await orchestrator.health_check()
                await websocket.send_json({
                    "type": "health",
                    "data": health
                })
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": str(e)}
                })
                
        else:
            await websocket.send_json({
                "type": "error",
                "data": {"message": f"Unknown message type: {msg_type}"}
            })
            
    except json.JSONDecodeError:
        await websocket.send_json({
            "type": "error",
            "data": {"message": "Invalid JSON"}
        })
    except Exception as e:
        logger.error(f"Error handling client message: {e}")
        await websocket.send_json({
            "type": "error",
            "data": {"message": str(e)}
        })


@websocket_router.websocket("/ws/signals/{symbol}")
async def symbol_websocket_endpoint(websocket: WebSocket, symbol: str):
    """
    Symbol-specific WebSocket endpoint.
    
    Only receives signals for the specified symbol.
    """
    await websocket.accept()
    
    # Send welcome message
    await websocket.send_json({
        "type": "connected",
        "data": {
            "message": f"Connected to signal stream for {symbol}",
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat()
        }
    })
    
    # Create a filtered callback for this symbol
    async def symbol_callback(signal_data: dict) -> None:
        if signal_data.get("data", {}).get("symbol") == symbol:
            try:
                await websocket.send_json(signal_data)
            except Exception:
                pass
    
    ws_output = get_websocket_output()
    
    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0
                )
                
                message = json.loads(data)
                if message.get("type") == "pong":
                    continue
                    
            except asyncio.TimeoutError:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected from {symbol}")
    except Exception as e:
        logger.error(f"WebSocket error for {symbol}: {e}")
