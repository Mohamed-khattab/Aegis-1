"""
Message Queue Output Plug for Aegis-1

Publish signals to RabbitMQ for downstream processing.
Based on PRD Section 5 - Output Plug 05: Message Queue Output.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

import aio_pika
from aio_pika import Message, DeliveryMode

from outputs.base import BaseOutput, OutputStatus
from models.signals import Signal
from config.settings import settings


logger = logging.getLogger(__name__)


class MessageQueueOutput(BaseOutput):
    """
    Message Queue output plug using RabbitMQ.
    
    From PRD:
    - Requirement: Publish signals to message queues for downstream processing
    - Use Case: Enables microservices architecture where other systems consume 
      signals asynchronously
    - Format: JSON serialization
    - Guarantees: At-least-once delivery with idempotency keys
    """
    
    # Exchange and queue names
    EXCHANGE_NAME = "aegis.signals"
    QUEUE_NAME = "aegis.signals.queue"
    ROUTING_KEY = "signal.new"
    
    def __init__(
        self,
        output_id: str = "message_queue",
        rabbitmq_url: str = None,
        exchange_name: str = None,
        queue_name: str = None
    ):
        """
        Initialize Message Queue output.
        
        Args:
            output_id: Unique identifier
            rabbitmq_url: RabbitMQ connection URL
            exchange_name: Exchange name
            queue_name: Queue name
        """
        super().__init__(output_id)
        
        self.rabbitmq_url = rabbitmq_url or settings.rabbitmq_url
        self.exchange_name = exchange_name or self.EXCHANGE_NAME
        self.queue_name = queue_name or self.QUEUE_NAME
        
        self._connection: Optional[aio_pika.RobustConnection] = None
        self._channel: Optional[aio_pika.Channel] = None
        self._exchange: Optional[aio_pika.Exchange] = None
    
    async def initialize(self) -> None:
        """Initialize RabbitMQ connection."""
        try:
            # Create connection
            self._connection = await aio_pika.connect_robust(
                self.rabbitmq_url,
                client_properties={"client_name": "aegis-1"}
            )
            
            # Create channel
            self._channel = await self._connection.channel()
            
            # Declare exchange
            self._exchange = await self._channel.declare_exchange(
                self.exchange_name,
                aio_pika.ExchangeType.TOPIC,
                durable=True
            )
            
            # Declare queue
            queue = await self._channel.declare_queue(
                self.queue_name,
                durable=True
            )
            
            # Bind queue to exchange
            await queue.bind(self._exchange, routing_key="signal.*")
            
            self.status = OutputStatus.ACTIVE
            logger.info(f"Message Queue output connected to {self.rabbitmq_url}")
            
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            self.status = OutputStatus.ERROR
            raise
    
    async def shutdown(self) -> None:
        """Close RabbitMQ connection."""
        if self._channel:
            await self._channel.close()
        if self._connection:
            await self._connection.close()
        
        self.status = OutputStatus.INACTIVE
        logger.info("Message Queue output disconnected")
    
    async def send(self, signal: Signal) -> bool:
        """
        Publish signal to message queue.
        
        Args:
            signal: Signal to publish
        
        Returns:
            True if successful
        """
        if not self._exchange:
            logger.error("RabbitMQ not connected")
            return False
        
        try:
            # Build message
            message_body = self._build_message_body(signal)
            
            # Create message with idempotency key
            message = Message(
                body=json.dumps(message_body).encode(),
                delivery_mode=DeliveryMode.PERSISTENT,
                message_id=str(signal.id),  # Idempotency key
                timestamp=datetime.utcnow(),
                content_type="application/json",
                headers={
                    "signal_action": signal.action.value,
                    "signal_symbol": signal.symbol,
                    "signal_confidence": str(signal.confidence),
                    "is_critical": str(signal.is_critical)
                }
            )
            
            # Determine routing key based on action
            routing_key = f"signal.{signal.action.value.lower()}"
            
            # Publish
            await self._exchange.publish(
                message,
                routing_key=routing_key
            )
            
            logger.debug(
                f"Signal {signal.id} published to {routing_key}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Error publishing to RabbitMQ: {e}")
            return False
    
    def _build_message_body(self, signal: Signal) -> dict[str, Any]:
        """Build message body from signal."""
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
            "metadata": signal.metadata,
            "is_critical": signal.is_critical,
            "is_actionable": signal.is_actionable
        }
    
    async def health_check(self) -> bool:
        """Check RabbitMQ connection health."""
        if not self._connection:
            return False
        return not self._connection.is_closed


class SignalConsumer:
    """
    Consumer for signals from the message queue.
    
    Used by downstream services to process signals.
    """
    
    def __init__(
        self,
        rabbitmq_url: str = None,
        queue_name: str = None
    ):
        """Initialize consumer."""
        self.rabbitmq_url = rabbitmq_url or settings.rabbitmq_url
        self.queue_name = queue_name or MessageQueueOutput.QUEUE_NAME
        
        self._connection: Optional[aio_pika.RobustConnection] = None
        self._channel: Optional[aio_pika.Channel] = None
        self._queue: Optional[aio_pika.Queue] = None
    
    async def connect(self) -> None:
        """Connect to RabbitMQ."""
        self._connection = await aio_pika.connect_robust(self.rabbitmq_url)
        self._channel = await self._connection.channel()
        
        # Set QoS
        await self._channel.set_qos(prefetch_count=10)
        
        # Get queue
        self._queue = await self._channel.declare_queue(
            self.queue_name,
            durable=True
        )
        
        logger.info(f"Signal consumer connected to {self.queue_name}")
    
    async def disconnect(self) -> None:
        """Disconnect from RabbitMQ."""
        if self._channel:
            await self._channel.close()
        if self._connection:
            await self._connection.close()
    
    async def consume(self, callback: callable) -> None:
        """
        Start consuming signals.
        
        Args:
            callback: Async function to call with each signal dict
        """
        if not self._queue:
            raise RuntimeError("Not connected")
        
        async with self._queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    try:
                        signal_data = json.loads(message.body.decode())
                        await callback(signal_data)
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
