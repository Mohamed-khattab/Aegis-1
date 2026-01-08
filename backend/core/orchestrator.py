"""
Core Orchestrator for Aegis-1

Coordinates all plugs and manages the signal generation workflow.
Based on PRD Section 2 and AC Section 1.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Optional

from core.blackboard import Blackboard
from core.state_manager import StateManager, AgentState, create_initial_state
from core.dynamic_weighting import DynamicWeighting
from plugs.base import BasePlug, PlugStatus
from plugs.news_sentry import NewsSentryPlug
from plugs.gemini_vector import GeminiVectorPlug
from plugs.quant_engine import QuantEnginePlug
from plugs.risk_analyst import RiskAnalystPlug
from models.signals import Signal, SignalAction, RiskDecision, BlackboardSnapshot
from models.market_data import MarketDataBundle
from db.timescale import get_timescale_client
from db.redis_client import get_redis_client
from config.settings import settings


logger = logging.getLogger(__name__)


class CoreOrchestrator:
    """
    Core Orchestrator for the Aegis-1 trading system.
    
    From PRD:
    - Coordinates all plugs in the Intelligence Layer
    - Uses Blackboard for shared state
    - Performs consensus resolution
    - Manages dynamic weighting
    
    From AC:
    - AC-01: Must resolve conflicting signals within <100ms
    - AC-02: Every trade execution logged with "Reasoning Snapshot"
    """
    
    def __init__(self):
        """Initialize the Core Orchestrator."""
        self.blackboard = Blackboard()
        self.state_manager = StateManager()
        self.dynamic_weighting = DynamicWeighting()
        
        # Plugs
        self._plugs: dict[str, BasePlug] = {}
        self._plug_order: list[str] = []  # Execution order
        
        # Callbacks
        self._signal_callbacks: list[callable] = []
        
        # State
        self._initialized = False
        self._running = False
    
    async def initialize(self) -> None:
        """Initialize the orchestrator and all components."""
        logger.info("Initializing Core Orchestrator...")
        
        # Initialize blackboard
        await self.blackboard.initialize()
        
        # Build state machine graph
        self.state_manager.build_graph()
        
        # Initialize default plugs
        await self._initialize_plugs()
        
        self._initialized = True
        logger.info("Core Orchestrator initialized")
    
    async def _initialize_plugs(self) -> None:
        """Initialize all intelligence plugs."""
        # Create plugs
        plugs_config = [
            ("news_sentry", NewsSentryPlug()),
            ("gemini_vector", GeminiVectorPlug()),
            ("quant_engine", QuantEnginePlug()),
            ("risk_analyst", RiskAnalystPlug()),
        ]
        
        for plug_id, plug in plugs_config:
            try:
                await plug.initialize()
                self._plugs[plug_id] = plug
                self._plug_order.append(plug_id)
                
                # Set initial weight
                await self.blackboard.set_weight(plug_id, 1.0)
                
                logger.info(f"Plug {plug_id} initialized")
            except Exception as e:
                logger.error(f"Failed to initialize plug {plug_id}: {e}")
    
    async def shutdown(self) -> None:
        """Shutdown the orchestrator and all components."""
        logger.info("Shutting down Core Orchestrator...")
        
        self._running = False
        
        # Shutdown plugs
        for plug_id, plug in self._plugs.items():
            try:
                await plug.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down plug {plug_id}: {e}")
        
        # Shutdown blackboard
        await self.blackboard.shutdown()
        
        self._initialized = False
        logger.info("Core Orchestrator shutdown complete")
    
    async def generate_signal(
        self,
        symbol: str,
        market_data: MarketDataBundle
    ) -> Signal:
        """
        Generate a trading signal for a symbol.
        
        This is the main entry point for signal generation.
        
        Args:
            symbol: Trading symbol
            market_data: Market data bundle
        
        Returns:
            Final Signal with action, confidence, and reasoning
        """
        if not self._initialized:
            raise RuntimeError("Orchestrator not initialized")
        
        start_time = time.perf_counter()
        
        # Create initial state
        state = create_initial_state(symbol, market_data)
        
        # Gather signals from all plugs
        plug_signals = await self._gather_plug_signals(market_data)
        
        # Get current weights
        weights = self.dynamic_weighting.get_all_weights()
        for plug_id in self._plugs.keys():
            if plug_id not in weights:
                weights[plug_id] = 1.0
        
        # Update state with signals and weights
        state["plug_signals"] = {
            plug_id: signal.to_dict()
            for plug_id, signal in plug_signals.items()
        }
        state["plug_weights"] = weights
        
        # Check consensus latency requirement (AC-01: <100ms)
        consensus_start = time.perf_counter()
        
        # Run state machine
        final_state = await self.state_manager.run(state)
        
        consensus_time = (time.perf_counter() - consensus_start) * 1000
        if consensus_time > settings.max_consensus_latency_ms:
            logger.warning(
                f"AC-01 violation: Consensus took {consensus_time:.1f}ms "
                f"(limit: {settings.max_consensus_latency_ms}ms)"
            )
        
        # Build final signal
        final_signal_data = final_state.get("final_signal", {})
        
        signal = Signal(
            timestamp=datetime.utcnow(),
            action=SignalAction(final_signal_data.get("action", "HOLD")),
            symbol=symbol,
            confidence=final_signal_data.get("confidence", 0.0),
            position_size=final_signal_data.get("position_size", 0.0),
            reasoning=final_signal_data.get("reasoning", ""),
            risk_score=final_signal_data.get("risk_score", 0.0),
            risk_decision=RiskDecision(
                final_signal_data.get("risk_decision", "EXECUTE")
            ),
            plug_contributions=final_signal_data.get("plug_contributions", {}),
            plug_signals=list(plug_signals.values())
        )
        
        # Calculate total latency
        total_time = (time.perf_counter() - start_time) * 1000
        
        # Check e2e latency (AC: <1.2s for AI trades)
        if total_time > settings.max_e2e_latency_ms:
            logger.warning(
                f"E2E latency warning: {total_time:.1f}ms "
                f"(target: {settings.max_e2e_latency_ms}ms)"
            )
        
        # Store signal
        await self._store_signal(signal, final_state)
        
        # Record predictions for dynamic weighting
        self._record_predictions(plug_signals)
        
        # Notify callbacks
        await self._notify_signal(signal)
        
        logger.info(
            f"Signal generated for {symbol}: {signal.action.value} "
            f"(confidence: {signal.confidence:.2f}, latency: {total_time:.1f}ms)"
        )
        
        return signal
    
    async def _gather_plug_signals(
        self,
        market_data: MarketDataBundle
    ) -> dict[str, Any]:
        """
        Gather signals from all active plugs in parallel.
        
        Returns:
            Dict of plug_id -> PlugSignal
        """
        signals = {}
        
        # Create tasks for all active plugs
        tasks = []
        plug_ids = []
        
        for plug_id in self._plug_order:
            plug = self._plugs.get(plug_id)
            if plug and plug.status == PlugStatus.ACTIVE:
                tasks.append(plug.safe_generate_signal(market_data))
                plug_ids.append(plug_id)
        
        # Run all plugs in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for plug_id, result in zip(plug_ids, results):
            if isinstance(result, Exception):
                logger.error(f"Plug {plug_id} error: {result}")
                continue
            
            signals[plug_id] = result
            
            # Write to blackboard
            await self.blackboard.write_signal(plug_id, result)
        
        return signals
    
    async def _store_signal(
        self,
        signal: Signal,
        state: AgentState
    ) -> None:
        """
        Store signal and create audit snapshot.
        
        AC-02: Every trade execution must be logged with a 
        "Reasoning Snapshot" showing exact contribution percentage of each plug.
        """
        try:
            # Store signal in database
            db = get_timescale_client()
            await db.insert_signal(signal)
            
            # Create and store audit snapshot
            snapshot = await self.blackboard.create_snapshot(signal)
            await db.insert_audit_snapshot(snapshot)
            
            logger.debug(f"Signal {signal.id} stored with audit snapshot")
            
        except Exception as e:
            logger.error(f"Error storing signal: {e}")
    
    def _record_predictions(self, plug_signals: dict[str, Any]) -> None:
        """Record predictions for dynamic weighting."""
        for plug_id, signal in plug_signals.items():
            weight = self.dynamic_weighting.get_weight(plug_id)
            self.dynamic_weighting.record_prediction(
                plug_id=plug_id,
                predicted_direction=signal.direction,
                confidence=signal.confidence,
                current_weight=weight
            )
    
    async def record_outcome(
        self,
        symbol: str,
        actual_direction: float
    ) -> None:
        """
        Record actual market outcome for dynamic weighting updates.
        
        Should be called after price movement is observed.
        
        Args:
            symbol: Trading symbol
            actual_direction: Actual price direction (-1 to 1)
        """
        for plug_id in self._plugs.keys():
            self.dynamic_weighting.record_outcome(plug_id, actual_direction)
        
        # Update weights in blackboard
        weights = self.dynamic_weighting.get_all_weights()
        for plug_id, weight in weights.items():
            await self.blackboard.set_weight(plug_id, weight)
    
    def add_signal_callback(self, callback: callable) -> None:
        """Add callback to be called when signals are generated."""
        self._signal_callbacks.append(callback)
    
    def remove_signal_callback(self, callback: callable) -> None:
        """Remove a signal callback."""
        if callback in self._signal_callbacks:
            self._signal_callbacks.remove(callback)
    
    async def _notify_signal(self, signal: Signal) -> None:
        """Notify all callbacks of new signal."""
        for callback in self._signal_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(signal)
                else:
                    callback(signal)
            except Exception as e:
                logger.error(f"Error in signal callback: {e}")
    
    # ===================
    # Plug Management
    # ===================
    
    def get_plug(self, plug_id: str) -> Optional[BasePlug]:
        """Get a plug by ID."""
        return self._plugs.get(plug_id)
    
    def get_all_plugs(self) -> dict[str, BasePlug]:
        """Get all plugs."""
        return dict(self._plugs)
    
    async def enable_plug(self, plug_id: str) -> bool:
        """Enable a disabled plug."""
        plug = self._plugs.get(plug_id)
        if plug:
            if plug.status == PlugStatus.ISOLATED:
                plug.reactivate()
            plug.status = PlugStatus.ACTIVE
            return True
        return False
    
    async def disable_plug(self, plug_id: str) -> bool:
        """Disable a plug."""
        plug = self._plugs.get(plug_id)
        if plug:
            plug.status = PlugStatus.INACTIVE
            return True
        return False
    
    async def set_plug_weight(self, plug_id: str, weight: float) -> bool:
        """Set weight for a specific plug."""
        if plug_id not in self._plugs:
            return False
        
        self.dynamic_weighting.set_weight(plug_id, weight)
        await self.blackboard.set_weight(plug_id, weight)
        return True
    
    # ===================
    # Status and Monitoring
    # ===================
    
    async def get_status(self) -> dict[str, Any]:
        """Get orchestrator status for monitoring."""
        plug_statuses = {}
        for plug_id, plug in self._plugs.items():
            plug_statuses[plug_id] = plug.get_status()
        
        blackboard_summary = await self.blackboard.get_state_summary()
        weights = self.dynamic_weighting.get_all_weights()
        
        return {
            "initialized": self._initialized,
            "running": self._running,
            "plugs": plug_statuses,
            "weights": weights,
            "blackboard": blackboard_summary,
            "performance": self.dynamic_weighting.get_performance_summary()
        }
    
    async def health_check(self) -> dict[str, Any]:
        """Perform health check on all components."""
        redis = get_redis_client()
        db = get_timescale_client()
        
        return {
            "orchestrator": self._initialized,
            "blackboard": await self.blackboard._redis.health_check() if self.blackboard._redis else False,
            "redis": await redis.health_check(),
            "database": await db.health_check(),
            "plugs": {
                plug_id: plug.status == PlugStatus.ACTIVE
                for plug_id, plug in self._plugs.items()
            }
        }
