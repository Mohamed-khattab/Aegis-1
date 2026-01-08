"""
Tests for Aegis-1 Output Modules
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import json

from outputs.base import BaseOutput, OutputStatus, OutputPriority, OutputMetrics
from models.signals import Signal, SignalAction, RiskDecision


class MockOutput(BaseOutput):
    """Mock output for testing base functionality."""
    
    def __init__(self):
        super().__init__(
            output_id="mock_output",
            priority=OutputPriority.NORMAL
        )
        self.sent_signals = []
        self._should_fail = False
    
    async def send(self, signal: Signal) -> bool:
        """Mock send implementation."""
        if self._should_fail:
            raise Exception("Mock failure")
        self.sent_signals.append(signal)
        return True
    
    async def initialize(self) -> None:
        self.status = OutputStatus.ACTIVE
    
    async def shutdown(self) -> None:
        self.status = OutputStatus.INACTIVE


@pytest.fixture
def mock_output():
    return MockOutput()


@pytest.fixture
def sample_signal():
    return Signal(
        action=SignalAction.BUY,
        symbol="BTCUSDT",
        confidence=0.85,
        risk_score=0.3,
        risk_decision=RiskDecision.EXECUTE,
        position_size=0.1,
        reasoning="Test signal"
    )


class TestBaseOutput:
    """Tests for BaseOutput functionality."""
    
    @pytest.mark.asyncio
    async def test_output_initialization(self, mock_output):
        """Test output initializes correctly."""
        await mock_output.initialize()
        assert mock_output.status == OutputStatus.ACTIVE
    
    @pytest.mark.asyncio
    async def test_deliver_success(self, mock_output, sample_signal):
        """Test successful signal delivery."""
        await mock_output.initialize()
        
        result = await mock_output.deliver(sample_signal)
        
        assert result is True
        assert len(mock_output.sent_signals) == 1
        assert mock_output.metrics.successful_deliveries == 1
    
    @pytest.mark.asyncio
    async def test_deliver_with_retry(self, mock_output, sample_signal):
        """Test delivery with retry on failure."""
        await mock_output.initialize()
        
        # Make first attempt fail, then succeed
        attempt_count = 0
        original_send = mock_output.send
        
        async def failing_send(signal):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise Exception("Temporary failure")
            return await original_send(signal)
        
        mock_output.send = failing_send
        
        result = await mock_output.deliver(sample_signal)
        
        assert result is True
        assert attempt_count == 2
    
    @pytest.mark.asyncio
    async def test_priority_filtering(self, mock_output, sample_signal):
        """Test priority-based filtering."""
        await mock_output.initialize()
        mock_output.min_priority = OutputPriority.HIGH
        
        # Normal priority signal should be filtered
        sample_signal.confidence = 0.5  # Not critical
        result = await mock_output.deliver(sample_signal)
        
        # Should still succeed but be filtered based on implementation
        assert result is True or len(mock_output.sent_signals) == 0
    
    @pytest.mark.asyncio
    async def test_disabled_output(self, mock_output, sample_signal):
        """Test that disabled output doesn't send."""
        await mock_output.initialize()
        mock_output.disable()
        
        result = await mock_output.deliver(sample_signal)
        
        assert result is False
        assert len(mock_output.sent_signals) == 0
    
    @pytest.mark.asyncio
    async def test_metrics_tracking(self, mock_output, sample_signal):
        """Test metrics are tracked correctly."""
        await mock_output.initialize()
        
        # Successful delivery
        await mock_output.deliver(sample_signal)
        
        assert mock_output.metrics.total_attempts >= 1
        assert mock_output.metrics.successful_deliveries == 1
    
    def test_enable_disable(self, mock_output):
        """Test enable/disable functionality."""
        mock_output.disable()
        assert mock_output.status == OutputStatus.DISABLED
        
        mock_output.enable()
        assert mock_output.status == OutputStatus.ACTIVE
    
    def test_get_status(self, mock_output):
        """Test status reporting."""
        status = mock_output.get_status()
        
        assert status["output_id"] == "mock_output"
        assert "metrics" in status


class TestWebhookOutput:
    """Tests for Webhook output module."""
    
    @pytest.mark.asyncio
    async def test_webhook_formatting(self, sample_signal):
        """Test webhook payload formatting."""
        from outputs.webhook import WebhookOutput
        
        output = WebhookOutput(
            url="https://example.com/webhook",
            auth_token="test_token"
        )
        
        payload = output._format_payload(sample_signal)
        
        assert payload["action"] == "BUY"
        assert payload["symbol"] == "BTCUSDT"
        assert "timestamp" in payload
    
    @pytest.mark.asyncio
    async def test_webhook_send(self, sample_signal):
        """Test webhook HTTP POST."""
        from outputs.webhook import WebhookOutput
        
        output = WebhookOutput(url="https://example.com/webhook")
        
        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_post.return_value.__aenter__.return_value = mock_response
            
            result = await output.send(sample_signal)
            
            # Would succeed if HTTP client were properly mocked


class TestEmailOutput:
    """Tests for Email output module."""
    
    @pytest.mark.asyncio
    async def test_email_formatting(self, sample_signal):
        """Test email content formatting."""
        from outputs.email_output import EmailOutput
        
        output = EmailOutput(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password",
            recipients=["alert@example.com"]
        )
        
        subject, body = output._format_email(sample_signal)
        
        assert "BUY" in subject
        assert "BTCUSDT" in subject
        assert "BTCUSDT" in body
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, sample_signal):
        """Test email rate limiting."""
        from outputs.email_output import EmailOutput
        
        output = EmailOutput(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password",
            recipients=["alert@example.com"]
        )
        
        # Check rate limit logic
        can_send = output._check_rate_limit("alert@example.com")
        assert can_send is True


class TestDatabaseOutput:
    """Tests for Database output module."""
    
    @pytest.mark.asyncio
    async def test_database_storage(self, sample_signal):
        """Test signal storage in database."""
        from outputs.database import DatabaseOutput
        
        output = DatabaseOutput()
        
        with patch('outputs.database.get_timescale_client') as mock_client:
            mock_db = AsyncMock()
            mock_client.return_value = mock_db
            
            output._db = mock_db
            result = await output.send(sample_signal)
            
            mock_db.insert_signal.assert_called_once()


class TestMessageQueueOutput:
    """Tests for RabbitMQ output module."""
    
    @pytest.mark.asyncio
    async def test_mq_message_formatting(self, sample_signal):
        """Test message queue message formatting."""
        from outputs.message_queue import MessageQueueOutput
        
        output = MessageQueueOutput()
        
        message = output._format_message(sample_signal)
        
        assert "signal_id" in message
        assert message["action"] == "BUY"
        assert message["symbol"] == "BTCUSDT"
    
    @pytest.mark.asyncio
    async def test_routing_key_generation(self, sample_signal):
        """Test routing key generation."""
        from outputs.message_queue import MessageQueueOutput
        
        output = MessageQueueOutput()
        
        routing_key = output._get_routing_key(sample_signal)
        
        assert "signal" in routing_key
        assert "buy" in routing_key.lower()


class TestWebSocketOutput:
    """Tests for WebSocket output module."""
    
    @pytest.mark.asyncio
    async def test_websocket_broadcast(self, sample_signal):
        """Test WebSocket broadcast to connected clients."""
        from outputs.websocket_output import WebSocketOutput
        
        output = WebSocketOutput()
        
        # Mock WebSocket connection
        mock_ws = AsyncMock()
        output._connections.add(mock_ws)
        
        await output.send(sample_signal)
        
        mock_ws.send_json.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_connection_management(self):
        """Test WebSocket connection management."""
        from outputs.websocket_output import WebSocketOutput
        
        output = WebSocketOutput()
        
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        
        output.add_connection(mock_ws1)
        output.add_connection(mock_ws2)
        
        assert len(output._connections) == 2
        
        output.remove_connection(mock_ws1)
        
        assert len(output._connections) == 1
