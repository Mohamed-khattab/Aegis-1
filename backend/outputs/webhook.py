"""
Webhook Output Plug for Aegis-1

HTTP POST webhook delivery to external systems.
Based on PRD Section 5 - Output Plug 01: Webhook Output.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

import aiohttp

from outputs.base import BaseOutput, OutputStatus
from models.signals import Signal
from config.settings import settings


logger = logging.getLogger(__name__)


class WebhookOutput(BaseOutput):
    """
    Webhook output plug for signal delivery.
    
    From PRD:
    - Requirement: HTTP POST webhook delivery to external systems
    - Configuration: Configurable endpoint URLs, authentication headers, 
      retry logic (exponential backoff)
    - Payload: JSON formatted Signal Object with optional custom fields
    - Reliability: Queue-based delivery with at-least-once semantics
    - Retries: Up to 3 times with 1-second, 5-second, and 30-second intervals
    - Security: Supports API key authentication, OAuth 2.0, and custom headers
    """
    
    def __init__(
        self,
        output_id: str = "webhook",
        url: str = None,
        auth_token: str = None,
        custom_headers: dict[str, str] = None,
        timeout: int = 30
    ):
        """
        Initialize Webhook output.
        
        Args:
            output_id: Unique identifier
            url: Webhook endpoint URL
            auth_token: Authentication token (if using bearer auth)
            custom_headers: Additional headers to send
            timeout: Request timeout in seconds
        """
        super().__init__(output_id)
        
        self.url = url or settings.webhook_url
        self.auth_token = auth_token or settings.webhook_auth_token
        self.custom_headers = custom_headers or {}
        self.timeout = timeout
        
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self) -> None:
        """Initialize HTTP session."""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        self.status = OutputStatus.ACTIVE
        logger.info(f"Webhook output initialized: {self.url}")
    
    async def shutdown(self) -> None:
        """Close HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None
        self.status = OutputStatus.INACTIVE
        logger.info("Webhook output shutdown")
    
    async def send(self, signal: Signal) -> bool:
        """
        Send signal to webhook endpoint.
        
        Args:
            signal: Signal to send
        
        Returns:
            True if successful
        """
        if not self.url:
            logger.warning("Webhook URL not configured")
            return False
        
        if not self._session:
            await self.initialize()
        
        # Build headers
        headers = {
            "Content-Type": "application/json",
            **self.custom_headers
        }
        
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        
        # Build payload
        payload = self._build_payload(signal)
        
        try:
            async with self._session.post(
                self.url,
                json=payload,
                headers=headers
            ) as response:
                if response.status == 200 or response.status == 201:
                    logger.info(f"Webhook delivery successful: {signal.id}")
                    return True
                else:
                    body = await response.text()
                    logger.error(
                        f"Webhook failed: {response.status} - {body[:200]}"
                    )
                    return False
                    
        except asyncio.TimeoutError:
            logger.error(f"Webhook timeout for {self.url}")
            return False
        except aiohttp.ClientError as e:
            logger.error(f"Webhook client error: {e}")
            return False
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return False
    
    def _build_payload(self, signal: Signal) -> dict[str, Any]:
        """Build JSON payload from signal."""
        return {
            "timestamp": signal.timestamp.isoformat(),
            "action": signal.action.value,
            "symbol": signal.symbol,
            "confidence": signal.confidence,
            "position_size": signal.position_size,
            "reasoning": signal.reasoning,
            "risk_score": signal.risk_score,
            "expiry": signal.expiry.isoformat() if signal.expiry else None,
            "signal_id": str(signal.id),
            "risk_decision": signal.risk_decision.value,
            "plug_contributions": signal.plug_contributions,
            "metadata": signal.metadata
        }
