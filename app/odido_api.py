"""
Odido API client for interacting with the Odido mobile carrier API.

This module provides functionality to:
- Authenticate with the Odido API
- Fetch available bundle information
- Purchase bundles using buying codes
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("odido.api")

ODIDO_BASE_URL = "https://capi.odido.nl"
DEFAULT_USER_AGENT = "T-Mobile 5.3.28 (Android 10; 10)"
DEFAULT_BUYING_CODE = "A0DAY01"


@dataclass
class Bundle:
    """Represents an Odido roaming bundle."""

    buying_code: str
    zone_color: str
    remaining_bytes: float
    remaining_mb: float
    description: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "buying_code": self.buying_code,
            "zone_color": self.zone_color,
            "remaining_bytes": self.remaining_bytes,
            "remaining_mb": self.remaining_mb,
            "description": self.description,
        }


@dataclass
class Subscription:
    """Represents an Odido subscription."""

    subscription_url: str
    phone_number: Optional[str] = None
    link_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "subscription_url": self.subscription_url,
            "phone_number": self.phone_number,
            "link_id": self.link_id,
        }


class OdidoAPIError(Exception):
    """Base exception for Odido API errors."""

    pass


class OdidoAuthError(OdidoAPIError):
    """Authentication error with the Odido API."""

    pass


class OdidoAPI:
    """Client for interacting with the Odido API."""

    def __init__(
        self,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        """
        Initialize the Odido API client.

        Args:
            user_id: The Odido user ID
            access_token: The Odido access/bearer token
        """
        self.user_id = user_id or os.getenv("ODIDO_USER_ID")
        self.access_token = access_token or os.getenv("ODIDO_TOKEN")

        self._session: Optional[requests.Session] = None
        self._subscription_url: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        """Check if the API client has valid credentials configured."""
        return bool(self.user_id and self.access_token)

    def _get_session(self) -> requests.Session:
        """Get or create an HTTP session with retry configuration."""
        if self._session is None:
            self._session = requests.Session()
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self._session.mount("https://", adapter)

        # Set headers for each request
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.access_token}",
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "application/json",
            }
        )
        return self._session

    def _handle_response(
        self, response: requests.Response, require_json: bool = True
    ) -> Dict[str, Any]:
        """Handle API response and check for errors."""
        if not response.ok:
            logger.error(f"API request failed: {response.status_code} {response.reason}")
            if response.status_code == 401:
                raise OdidoAuthError("Invalid or expired access token")
            raise OdidoAPIError(f"API error: {response.status_code} {response.reason}")

        try:
            return response.json()
        except json.JSONDecodeError:
            if require_json:
                raise OdidoAPIError(f"Expected JSON response, got: {response.text}")
            return {"raw": response.text}

    def get_subscriptions(self) -> List[Subscription]:
        """
        Fetch the user's subscriptions.

        Returns:
            List of Subscription objects
        """
        if not self.is_configured:
            raise OdidoAPIError("API client not configured with credentials")

        session = self._get_session()
        logger.info("Fetching subscription details...")

        response = session.get(
            f"{ODIDO_BASE_URL}/{self.user_id}/linkedsubscriptions"
        )
        data = self._handle_response(response)

        subscriptions = []
        for sub in data.get("subscriptions", []):
            subscription = Subscription(
                subscription_url=sub.get("SubscriptionURL", ""),
                phone_number=sub.get("PhoneNumber"),
                link_id=sub.get("LinkId"),
            )
            subscriptions.append(subscription)

        if subscriptions and not self._subscription_url:
            self._subscription_url = subscriptions[0].subscription_url

        return subscriptions

    def get_roaming_bundles(
        self, subscription_url: Optional[str] = None
    ) -> List[Bundle]:
        """
        Fetch roaming bundle information for a subscription.

        Args:
            subscription_url: The subscription URL, or uses the first subscription

        Returns:
            List of Bundle objects
        """
        if not self.is_configured:
            raise OdidoAPIError("API client not configured with credentials")

        url = subscription_url or self._subscription_url
        if not url:
            # Fetch subscriptions first to get the URL
            subs = self.get_subscriptions()
            if not subs:
                raise OdidoAPIError("No subscriptions found")
            url = subs[0].subscription_url

        session = self._get_session()
        logger.info("Fetching roaming bundle information...")

        response = session.get(f"{url}/roamingbundles")
        data = self._handle_response(response)

        bundles = []
        for bundle in data.get("Bundles", []):
            remaining = bundle.get("Remaining", {})
            remaining_bytes = remaining.get("Value", 0)
            bundles.append(
                Bundle(
                    buying_code=bundle.get("BuyingCode", ""),
                    zone_color=bundle.get("ZoneColor", ""),
                    remaining_bytes=remaining_bytes,
                    remaining_mb=round(remaining_bytes / 1024, 2),
                    description=bundle.get("Description"),
                )
            )

        return bundles

    def get_remaining_data_mb(
        self, subscription_url: Optional[str] = None, zone_color: str = "NL"
    ) -> float:
        """
        Get the total remaining data in MB for a specific zone.

        Args:
            subscription_url: The subscription URL
            zone_color: The zone to filter by (default: "NL")

        Returns:
            Total remaining MB for the specified zone
        """
        bundles = self.get_roaming_bundles(subscription_url)
        total_bytes = sum(
            b.remaining_bytes for b in bundles if b.zone_color == zone_color
        )
        return round(total_bytes / 1024, 2)

    def buy_bundle(
        self,
        buying_code: str = DEFAULT_BUYING_CODE,
        subscription_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purchase a bundle using the specified buying code.

        Args:
            buying_code: The bundle buying code (default: A0DAY01)
            subscription_url: The subscription URL

        Returns:
            API response data
        """
        if not self.is_configured:
            raise OdidoAPIError("API client not configured with credentials")

        url = subscription_url or self._subscription_url
        if not url:
            subs = self.get_subscriptions()
            if not subs:
                raise OdidoAPIError("No subscriptions found")
            url = subs[0].subscription_url

        session = self._get_session()
        logger.info(f"Purchasing bundle with code: {buying_code}")

        payload = {"Bundles": [{"BuyingCode": buying_code}]}
        response = session.post(f"{url}/roamingbundles", json=payload)

        # Note: Odido API returns 202 for successful bundle purchase
        if response.status_code == 202:
            logger.info(f"Successfully requested bundle purchase: {buying_code}")
            return {"success": True, "buying_code": buying_code}

        return self._handle_response(response, require_json=False)

    def get_available_bundle_codes(self) -> List[str]:
        """
        Get a list of known available bundle codes.

        Note: The Odido API does not provide an endpoint to list available
        bundle codes. This returns commonly used codes based on reference
        implementations.

        Returns:
            List of known bundle buying codes
        """
        # These are common bundle codes based on the reference projects
        # The actual available codes may vary based on the user's subscription
        return [
            "A0DAY01",  # 2GB daily bundle
            "A0DAY05",  # 5GB daily bundle
        ]
