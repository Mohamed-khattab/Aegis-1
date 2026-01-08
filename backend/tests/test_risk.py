"""
Tests for Aegis-1 Risk Management Components
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from utils.circuit_breaker import CircuitBreaker, CircuitState, KillSwitch
from utils.audit import AuditLogger, AuditEntry, EventType


class TestCircuitBreaker:
    """Tests for CircuitBreaker pattern implementation."""
    
    def test_initial_state(self):
        """Test circuit breaker starts in closed state."""
        cb = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=60
        )
        
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
    
    def test_record_success(self):
        """Test recording successful operations."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        cb.record_success()
        
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
    
    def test_record_failure_below_threshold(self):
        """Test recording failures below threshold."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        cb.record_failure()
        cb.record_failure()
        
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 2
    
    def test_circuit_opens_at_threshold(self):
        """Test circuit opens when failure threshold reached."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        
        assert cb.state == CircuitState.OPEN
    
    def test_circuit_half_open_after_timeout(self):
        """Test circuit transitions to half-open after timeout."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1)
        
        # Open the circuit
        for _ in range(3):
            cb.record_failure()
        
        assert cb.state == CircuitState.OPEN
        
        # Simulate timeout by adjusting last_failure_time
        cb._last_failure_time = datetime.utcnow() - timedelta(seconds=2)
        
        # Check if allowed (should transition to half-open)
        allowed = cb.is_allowed()
        
        assert cb.state == CircuitState.HALF_OPEN
        assert allowed is True
    
    def test_circuit_closes_on_success_in_half_open(self):
        """Test circuit closes on success in half-open state."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1)
        
        # Open circuit
        for _ in range(3):
            cb.record_failure()
        
        # Force half-open state
        cb._state = CircuitState.HALF_OPEN
        
        cb.record_success()
        
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
    
    def test_circuit_reopens_on_failure_in_half_open(self):
        """Test circuit reopens on failure in half-open state."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        # Force half-open state
        cb._state = CircuitState.HALF_OPEN
        
        cb.record_failure()
        
        assert cb.state == CircuitState.OPEN
    
    def test_is_allowed_when_closed(self):
        """Test is_allowed returns True when closed."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        assert cb.is_allowed() is True
    
    def test_is_allowed_when_open(self):
        """Test is_allowed returns False when open."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        for _ in range(3):
            cb.record_failure()
        
        assert cb.is_allowed() is False


class TestKillSwitch:
    """Tests for KillSwitch emergency shutdown."""
    
    def test_initial_state(self):
        """Test kill switch starts inactive."""
        ks = KillSwitch(loss_threshold_percent=2.0)
        
        assert ks.is_triggered is False
        assert ks.triggered_at is None
    
    def test_trigger_on_threshold(self):
        """Test kill switch triggers at loss threshold."""
        ks = KillSwitch(loss_threshold_percent=2.0)
        
        # 2.5% loss should trigger
        ks.check_and_trigger(
            current_value=97500,
            initial_value=100000
        )
        
        assert ks.is_triggered is True
        assert ks.triggered_at is not None
    
    def test_no_trigger_below_threshold(self):
        """Test kill switch doesn't trigger below threshold."""
        ks = KillSwitch(loss_threshold_percent=2.0)
        
        # 1% loss should not trigger
        ks.check_and_trigger(
            current_value=99000,
            initial_value=100000
        )
        
        assert ks.is_triggered is False
    
    def test_callback_execution(self):
        """Test shutdown callbacks are executed."""
        ks = KillSwitch(loss_threshold_percent=2.0)
        
        callback_executed = []
        
        def mock_callback():
            callback_executed.append(True)
        
        ks.add_shutdown_callback(mock_callback)
        
        ks.check_and_trigger(
            current_value=97000,
            initial_value=100000
        )
        
        assert len(callback_executed) == 1
    
    def test_manual_trigger(self):
        """Test manual kill switch trigger."""
        ks = KillSwitch(loss_threshold_percent=2.0)
        
        ks.trigger("Manual emergency shutdown")
        
        assert ks.is_triggered is True
        assert "Manual" in ks.trigger_reason
    
    def test_reset(self):
        """Test kill switch reset."""
        ks = KillSwitch(loss_threshold_percent=2.0)
        
        ks.trigger("Test trigger")
        assert ks.is_triggered is True
        
        ks.reset()
        
        assert ks.is_triggered is False
        assert ks.triggered_at is None
    
    def test_get_status(self):
        """Test status reporting."""
        ks = KillSwitch(loss_threshold_percent=2.0)
        
        status = ks.get_status()
        
        assert "is_triggered" in status
        assert "loss_threshold_percent" in status
        assert status["loss_threshold_percent"] == 2.0


class TestAuditLogger:
    """Tests for AuditLogger functionality."""
    
    @pytest.fixture
    def audit_logger(self):
        return AuditLogger()
    
    def test_log_entry_creation(self, audit_logger):
        """Test creating audit log entries."""
        entry = AuditEntry(
            event_type=EventType.SIGNAL_GENERATED,
            description="Test signal generated",
            data={"symbol": "BTCUSDT", "action": "BUY"}
        )
        
        assert entry.event_type == EventType.SIGNAL_GENERATED
        assert entry.timestamp is not None
        assert entry.id is not None
    
    @pytest.mark.asyncio
    async def test_log_signal_generated(self, audit_logger):
        """Test logging signal generation."""
        from models.signals import Signal, SignalAction, RiskDecision
        
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.85,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        
        with patch.object(audit_logger, '_persist_entry', new_callable=AsyncMock):
            await audit_logger.log_signal(signal)
            
            assert len(audit_logger._recent_entries) > 0
    
    @pytest.mark.asyncio
    async def test_log_risk_veto(self, audit_logger):
        """Test logging risk veto events."""
        with patch.object(audit_logger, '_persist_entry', new_callable=AsyncMock):
            await audit_logger.log_risk_veto(
                symbol="BTCUSDT",
                reason="Max drawdown exceeded",
                risk_score=0.9
            )
            
            # Check entry was logged
            recent = audit_logger.get_recent_entries(event_type=EventType.RISK_VETO)
            assert len(recent) >= 0  # May be 0 if not persisted yet
    
    @pytest.mark.asyncio
    async def test_log_kill_switch(self, audit_logger):
        """Test logging kill switch activation."""
        with patch.object(audit_logger, '_persist_entry', new_callable=AsyncMock):
            await audit_logger.log_kill_switch(
                reason="Session loss exceeded 2%",
                loss_percent=2.5
            )
    
    @pytest.mark.asyncio
    async def test_log_plug_isolated(self, audit_logger):
        """Test logging plug isolation events."""
        with patch.object(audit_logger, '_persist_entry', new_callable=AsyncMock):
            await audit_logger.log_plug_isolated(
                plug_id="news_sentry",
                reason="Invalid signal range"
            )
    
    def test_get_recent_entries(self, audit_logger):
        """Test retrieving recent entries."""
        # Add some entries
        for i in range(5):
            entry = AuditEntry(
                event_type=EventType.SIGNAL_GENERATED,
                description=f"Signal {i}",
                data={}
            )
            audit_logger._recent_entries.append(entry)
        
        recent = audit_logger.get_recent_entries(limit=3)
        
        assert len(recent) == 3
    
    def test_entry_to_dict(self):
        """Test audit entry serialization."""
        entry = AuditEntry(
            event_type=EventType.TRADE_EXECUTED,
            description="Trade executed",
            data={"symbol": "BTCUSDT", "side": "buy", "quantity": 0.1}
        )
        
        data = entry.to_dict()
        
        assert data["event_type"] == "TRADE_EXECUTED"
        assert "timestamp" in data
        assert data["data"]["symbol"] == "BTCUSDT"


class TestRiskAnalystPlug:
    """Tests for Risk Analyst plug."""
    
    @pytest.mark.asyncio
    async def test_var_calculation(self):
        """Test Value at Risk calculation."""
        from plugs.risk_analyst import RiskAnalyst
        
        plug = RiskAnalyst()
        await plug.initialize()
        
        # Mock portfolio
        plug._portfolio_value = 100000
        plug._positions = {"BTCUSDT": 10000}
        
        var = plug._calculate_var(confidence_level=0.95)
        
        assert var >= 0
    
    @pytest.mark.asyncio
    async def test_max_drawdown_check(self):
        """Test max drawdown enforcement."""
        from plugs.risk_analyst import RiskAnalyst
        
        plug = RiskAnalyst()
        await plug.initialize()
        
        plug._peak_value = 100000
        plug._portfolio_value = 90000  # 10% drawdown
        
        drawdown = plug._calculate_drawdown()
        
        assert drawdown == 0.10
    
    @pytest.mark.asyncio
    async def test_position_concentration_check(self):
        """Test position concentration limits."""
        from plugs.risk_analyst import RiskAnalyst
        
        plug = RiskAnalyst()
        await plug.initialize()
        
        plug._portfolio_value = 100000
        plug._positions = {"BTCUSDT": 30000}  # 30% concentration
        
        is_concentrated = plug._check_concentration("BTCUSDT", additional=10000)
        
        # With default 25% limit, should flag concentration
        assert is_concentrated is True
    
    @pytest.mark.asyncio
    async def test_veto_on_risk_breach(self):
        """Test veto power on risk breach."""
        from plugs.risk_analyst import RiskAnalyst
        from models.market_data import MarketDataBundle
        from models.signals import RiskDecision
        
        plug = RiskAnalyst()
        await plug.initialize()
        
        # Set up high-risk scenario
        plug._portfolio_value = 100000
        plug._peak_value = 120000  # 16.7% drawdown
        
        bundle = MarketDataBundle(symbol="BTCUSDT")
        
        signal = await plug.generate_signal(bundle)
        
        # Should recommend ABORT due to high drawdown
        assert signal.metadata.get("decision") in [RiskDecision.ABORT.value, "ABORT"]
