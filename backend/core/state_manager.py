"""
State Manager for Aegis-1

LangGraph-based state management for the agent orchestration.
Based on PRD Section 7: LangGraph to handle conversational state between agents.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Annotated, Optional, TypedDict
from enum import Enum

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from models.signals import Signal, PlugSignal, SignalAction, RiskDecision
from models.market_data import MarketDataBundle


logger = logging.getLogger(__name__)


class WorkflowPhase(str, Enum):
    """Phases of the signal generation workflow."""
    INIT = "init"
    GATHER_SIGNALS = "gather_signals"
    CONSENSUS = "consensus"
    RISK_CHECK = "risk_check"
    DEBATE = "debate"  # Adversarial debating for high-stakes
    FINALIZE = "finalize"
    COMPLETE = "complete"


class AgentState(TypedDict):
    """
    State schema for the LangGraph workflow.
    
    This represents the shared state that flows through
    all nodes in the signal generation graph.
    """
    # Current phase
    phase: WorkflowPhase
    
    # Input data
    symbol: str
    market_data: Optional[dict[str, Any]]
    
    # Plug signals
    plug_signals: dict[str, dict[str, Any]]
    
    # Weights
    plug_weights: dict[str, float]
    
    # Consensus result
    consensus_direction: float
    consensus_confidence: float
    consensus_reasoning: str
    
    # Risk analysis
    risk_decision: str  # EXECUTE or ABORT
    risk_score: float
    risk_reasoning: str
    suggested_position_size: float
    
    # Debate results (for high-stakes trades)
    bull_argument: str
    bear_argument: str
    debate_outcome: str
    
    # Final signal
    final_signal: Optional[dict[str, Any]]
    
    # Metadata
    start_time: str
    end_time: Optional[str]
    latency_ms: float
    errors: list[str]
    
    # Message history for debugging
    messages: Annotated[list[dict], add_messages]


def create_initial_state(
    symbol: str,
    market_data: Optional[MarketDataBundle] = None
) -> AgentState:
    """Create initial state for a new signal generation run."""
    return AgentState(
        phase=WorkflowPhase.INIT,
        symbol=symbol,
        market_data=market_data.to_dict() if market_data else None,
        plug_signals={},
        plug_weights={},
        consensus_direction=0.0,
        consensus_confidence=0.0,
        consensus_reasoning="",
        risk_decision=RiskDecision.EXECUTE.value,
        risk_score=0.0,
        risk_reasoning="",
        suggested_position_size=0.0,
        bull_argument="",
        bear_argument="",
        debate_outcome="",
        final_signal=None,
        start_time=datetime.utcnow().isoformat(),
        end_time=None,
        latency_ms=0.0,
        errors=[],
        messages=[]
    )


class StateManager:
    """
    LangGraph state manager for Aegis-1.
    
    Manages the workflow graph for signal generation:
    1. Gather signals from all plugs
    2. Calculate consensus
    3. Risk check
    4. Optional adversarial debate
    5. Finalize signal
    """
    
    def __init__(self):
        """Initialize state manager."""
        self._graph: Optional[StateGraph] = None
        self._compiled_graph = None
    
    def build_graph(self) -> StateGraph:
        """
        Build the LangGraph workflow.
        
        Returns:
            Compiled StateGraph for signal generation
        """
        # Create graph with state schema
        graph = StateGraph(AgentState)
        
        # Add nodes
        graph.add_node("init", self._init_node)
        graph.add_node("gather_signals", self._gather_signals_node)
        graph.add_node("consensus", self._consensus_node)
        graph.add_node("risk_check", self._risk_check_node)
        graph.add_node("debate", self._debate_node)
        graph.add_node("finalize", self._finalize_node)
        
        # Add edges
        graph.set_entry_point("init")
        graph.add_edge("init", "gather_signals")
        graph.add_edge("gather_signals", "consensus")
        graph.add_edge("consensus", "risk_check")
        
        # Conditional edge: debate only for high-stakes trades
        graph.add_conditional_edges(
            "risk_check",
            self._should_debate,
            {
                "debate": "debate",
                "finalize": "finalize"
            }
        )
        
        graph.add_edge("debate", "finalize")
        graph.add_edge("finalize", END)
        
        self._graph = graph
        self._compiled_graph = graph.compile()
        
        logger.info("State manager graph built")
        return self._compiled_graph
    
    def _init_node(self, state: AgentState) -> dict:
        """Initialize the workflow."""
        return {
            "phase": WorkflowPhase.GATHER_SIGNALS,
            "messages": [{
                "role": "system",
                "content": f"Starting signal generation for {state['symbol']}"
            }]
        }
    
    def _gather_signals_node(self, state: AgentState) -> dict:
        """
        Gather signals from all plugs.
        
        Note: Actual plug execution happens in the orchestrator.
        This node just marks the phase transition.
        """
        return {
            "phase": WorkflowPhase.CONSENSUS,
            "messages": [{
                "role": "system",
                "content": f"Gathered {len(state.get('plug_signals', {}))} plug signals"
            }]
        }
    
    def _consensus_node(self, state: AgentState) -> dict:
        """
        Calculate weighted consensus from plug signals.
        
        This is the core decision-making logic.
        """
        plug_signals = state.get("plug_signals", {})
        plug_weights = state.get("plug_weights", {})
        
        if not plug_signals:
            return {
                "phase": WorkflowPhase.RISK_CHECK,
                "consensus_direction": 0.0,
                "consensus_confidence": 0.0,
                "consensus_reasoning": "No plug signals available",
                "messages": [{
                    "role": "system",
                    "content": "No signals to process, defaulting to neutral"
                }]
            }
        
        # Calculate weighted consensus
        total_weight = 0.0
        weighted_direction = 0.0
        weighted_confidence = 0.0
        
        reasoning_parts = []
        
        for plug_id, signal_data in plug_signals.items():
            weight = plug_weights.get(plug_id, 1.0)
            direction = signal_data.get("direction", 0.0)
            confidence = signal_data.get("confidence", 0.0)
            
            # Contribution to consensus
            contribution = direction * confidence * weight
            weighted_direction += contribution
            weighted_confidence += confidence * weight
            total_weight += weight
            
            reasoning_parts.append(
                f"{plug_id}(w={weight:.2f}): {direction:+.2f}"
            )
        
        if total_weight > 0:
            final_direction = weighted_direction / total_weight
            final_confidence = weighted_confidence / total_weight
        else:
            final_direction = 0.0
            final_confidence = 0.0
        
        # Clamp values
        final_direction = max(-1.0, min(1.0, final_direction))
        final_confidence = max(0.0, min(1.0, final_confidence))
        
        reasoning = f"Consensus: {' | '.join(reasoning_parts)} => {final_direction:+.3f}"
        
        return {
            "phase": WorkflowPhase.RISK_CHECK,
            "consensus_direction": final_direction,
            "consensus_confidence": final_confidence,
            "consensus_reasoning": reasoning,
            "messages": [{
                "role": "assistant",
                "content": reasoning
            }]
        }
    
    def _risk_check_node(self, state: AgentState) -> dict:
        """
        Apply risk check from Risk Analyst plug.
        
        Note: Actual risk calculation happens in the plug.
        This node extracts the decision from plug signals.
        """
        plug_signals = state.get("plug_signals", {})
        risk_signal = plug_signals.get("risk_analyst", {})
        
        risk_decision = risk_signal.get("metadata", {}).get(
            "decision",
            RiskDecision.EXECUTE.value
        )
        risk_score = risk_signal.get("metadata", {}).get("risk_score", 0.0)
        risk_reasoning = risk_signal.get("logic", "No risk analysis available")
        position_size = risk_signal.get("metadata", {}).get(
            "suggested_position_size",
            0.01
        )
        
        return {
            "phase": WorkflowPhase.DEBATE if self._is_high_stakes(state) else WorkflowPhase.FINALIZE,
            "risk_decision": risk_decision,
            "risk_score": risk_score,
            "risk_reasoning": risk_reasoning,
            "suggested_position_size": position_size,
            "messages": [{
                "role": "system",
                "content": f"Risk check: {risk_decision}, score={risk_score:.2f}"
            }]
        }
    
    def _should_debate(self, state: AgentState) -> str:
        """Determine if adversarial debate is needed."""
        if self._is_high_stakes(state):
            return "debate"
        return "finalize"
    
    def _is_high_stakes(self, state: AgentState) -> bool:
        """
        Determine if this is a high-stakes trade requiring debate.
        
        High-stakes criteria:
        - High confidence (> 0.8)
        - Large position size
        - High risk score
        """
        confidence = state.get("consensus_confidence", 0.0)
        position_size = state.get("suggested_position_size", 0.0)
        risk_score = state.get("risk_score", 0.0)
        
        return (
            confidence > 0.8 and
            (position_size > 0.05 or risk_score > 0.5)
        )
    
    def _debate_node(self, state: AgentState) -> dict:
        """
        Adversarial debate between Bull and Bear agents.
        
        From PRD Section 8.B: Before a high-stakes trade, the system 
        spawns a "Bear Agent" and a "Bull Agent." They must "debate" 
        the trade logic using the shared Blackboard.
        """
        direction = state.get("consensus_direction", 0.0)
        confidence = state.get("consensus_confidence", 0.0)
        plug_signals = state.get("plug_signals", {})
        
        # Build arguments from plug signals
        bull_points = []
        bear_points = []
        
        for plug_id, signal_data in plug_signals.items():
            signal_direction = signal_data.get("direction", 0.0)
            logic = signal_data.get("logic", "")
            
            if signal_direction > 0.1:
                bull_points.append(f"{plug_id}: {logic[:100]}")
            elif signal_direction < -0.1:
                bear_points.append(f"{plug_id}: {logic[:100]}")
        
        bull_argument = "BULL CASE: " + "; ".join(bull_points) if bull_points else "No strong bullish signals"
        bear_argument = "BEAR CASE: " + "; ".join(bear_points) if bear_points else "No strong bearish signals"
        
        # Determine debate outcome
        bull_strength = len(bull_points)
        bear_strength = len(bear_points)
        
        if direction > 0:
            # Bullish consensus - bear needs to make strong case
            if bear_strength >= bull_strength and bear_strength > 1:
                outcome = "CAUTION: Bear arguments are compelling, reduce position"
                # Reduce confidence
                confidence *= 0.7
            else:
                outcome = "PROCEED: Bull case withstands scrutiny"
        else:
            # Bearish/neutral consensus - bull needs to make strong case
            if bull_strength >= bear_strength and bull_strength > 1:
                outcome = "RECONSIDER: Bull arguments warrant attention"
            else:
                outcome = "PROCEED: Original analysis confirmed"
        
        return {
            "phase": WorkflowPhase.FINALIZE,
            "bull_argument": bull_argument,
            "bear_argument": bear_argument,
            "debate_outcome": outcome,
            "consensus_confidence": confidence,  # May be adjusted
            "messages": [{
                "role": "assistant",
                "content": f"Debate: {outcome}"
            }]
        }
    
    def _finalize_node(self, state: AgentState) -> dict:
        """
        Finalize the signal based on all analysis.
        """
        end_time = datetime.utcnow()
        start_time = datetime.fromisoformat(state["start_time"])
        latency_ms = (end_time - start_time).total_seconds() * 1000
        
        # Determine action
        direction = state.get("consensus_direction", 0.0)
        confidence = state.get("consensus_confidence", 0.0)
        risk_decision = state.get("risk_decision", RiskDecision.EXECUTE.value)
        
        if risk_decision == RiskDecision.ABORT.value:
            action = SignalAction.HOLD.value
        elif direction > 0.1 and confidence > 0.5:
            action = SignalAction.BUY.value
        elif direction < -0.1 and confidence > 0.5:
            action = SignalAction.SELL.value
        else:
            action = SignalAction.HOLD.value
        
        # Build final signal
        final_signal = {
            "timestamp": end_time.isoformat(),
            "action": action,
            "symbol": state["symbol"],
            "confidence": confidence,
            "position_size": state.get("suggested_position_size", 0.0),
            "reasoning": state.get("consensus_reasoning", ""),
            "risk_score": state.get("risk_score", 0.0),
            "risk_decision": risk_decision,
            "plug_contributions": {
                plug_id: {
                    "direction": sig.get("direction", 0),
                    "confidence": sig.get("confidence", 0)
                }
                for plug_id, sig in state.get("plug_signals", {}).items()
            }
        }
        
        return {
            "phase": WorkflowPhase.COMPLETE,
            "final_signal": final_signal,
            "end_time": end_time.isoformat(),
            "latency_ms": latency_ms,
            "messages": [{
                "role": "assistant",
                "content": f"Final signal: {action} with {confidence:.1%} confidence"
            }]
        }
    
    async def run(self, initial_state: AgentState) -> AgentState:
        """
        Run the state machine to generate a signal.
        
        Args:
            initial_state: Starting state with market data
        
        Returns:
            Final state with signal
        """
        if self._compiled_graph is None:
            self.build_graph()
        
        # Run the graph
        final_state = await self._compiled_graph.ainvoke(initial_state)
        
        return final_state
    
    def get_graph_visualization(self) -> str:
        """Get a Mermaid diagram of the graph."""
        return """
        graph TD
            A[Init] --> B[Gather Signals]
            B --> C[Consensus]
            C --> D[Risk Check]
            D -->|High Stakes| E[Debate]
            D -->|Normal| F[Finalize]
            E --> F
            F --> G[Complete]
        """
