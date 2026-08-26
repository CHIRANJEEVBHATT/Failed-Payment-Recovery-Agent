import json
import logging
from typing import Any, Optional

import requests

from app.config import (
    RAZORPAY_BASE_URL,
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
)


# ---------------------------------------------------------
# Logging
# ---------------------------------------------------------

logger = logging.getLogger(
    "razorpay_api"
)

logger.setLevel(
    logging.INFO
)

if not logger.handlers:
    file_handler = logging.FileHandler(
        "logs/razorpay_api.log",
        encoding="utf-8",
    )

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    file_handler.setFormatter(
        formatter
    )

    logger.addHandler(
        file_handler
    )


class RazorpayClient:
    """
    Small Razorpay TEST MODE API client.

    This class is intentionally kept simple.

    Responsibilities:
        - Authenticate using Razorpay API credentials.
        - Send HTTP requests.
        - Log requests and responses.
        - Create Payment Links.
    """

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.key_id = (
            key_id
            if key_id is not None
            else RAZORPAY_KEY_ID
        )

        self.key_secret = (
            key_secret
            if key_secret is not None
            else RAZORPAY_KEY_SECRET
        )

        self.base_url = (
            base_url
            if base_url is not None
            else RAZORPAY_BASE_URL
        ).rstrip("/")

        self.session = requests.Session()

        self.session.auth = (
            self.key_id,
            self.key_secret,
        )

        self.session.headers.update(
            {
                "Content-Type": (
                    "application/json"
                ),
                "Accept": (
                    "application/json"
                ),
            }
        )

    # -----------------------------------------------------
    # Internal logging helpers
    # -----------------------------------------------------

    @staticmethod
    def _safe_json(
        value: Any,
    ) -> Any:
        """
        Convert an object into something that can safely
        be written to the API log.
        """

        if value is None:
            return None

        try:
            json.dumps(value)
            return value
        except (
            TypeError,
            ValueError,
        ):
            return str(value)

    def _log_request(
        self,
        method: str,
        url: str,
        payload: Optional[dict],
    ) -> None:
        """
        Log an outgoing API request.

        NOTE:
        Credentials are never included in the log.
        """

        logger.info(
            "API REQUEST | %s",
            json.dumps(
                {
                    "method": method,
                    "url": url,
                    "payload": self._safe_json(
                        payload
                    ),
                },
                default=str,
            ),
        )

    def _log_response(
        self,
        status_code: int,
        data: Any,
    ) -> None:
        """
        Log an API response.
        """

        logger.info(
            "API RESPONSE | %s",
            json.dumps(
                {
                    "status_code": status_code,
                    "data": self._safe_json(
                        data
                    ),
                },
                default=str,
            ),
        )

    # -----------------------------------------------------
    # Generic request
    # -----------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[dict] = None,
    ) -> dict:
        """
        Make an authenticated Razorpay API request.

        Returns a consistent response structure:

            {
                "success": bool,
                "status_code": int,
                "data": dict | None,
                "error": str | None,
                "request": dict
            }
        """

        url = (
            f"{self.base_url}/"
            f"{endpoint.lstrip('/')}"
        )

        self._log_request(
            method=method,
            url=url,
            payload=payload,
        )

        request_details = {
            "method": method,
            "url": url,
            "payload": payload,
        }

        try:
            response = self.session.request(
                method=method,
                url=url,
                json=payload,
                timeout=30,
            )

        except requests.RequestException as exc:
            error_message = str(exc)

            logger.error(
                "API FAILURE | "
                "Network error=%s",
                error_message,
            )

            return {
                "success": False,
                "status_code": None,
                "data": None,
                "error": error_message,
                "request": request_details,
            }

        # -------------------------------------------------
        # Parse response
        # -------------------------------------------------

        try:
            data = response.json()
        except ValueError:
            data = {
                "raw_response": response.text
            }

        self._log_response(
            status_code=response.status_code,
            data=data,
        )

        # -------------------------------------------------
        # Successful HTTP response
        # -------------------------------------------------

        if 200 <= response.status_code < 300:
            return {
                "success": True,
                "status_code": response.status_code,
                "data": data,
                "error": None,
                "request": request_details,
            }

        # -------------------------------------------------
        # Failed HTTP response
        # -------------------------------------------------

        error_message = (
            self._extract_error_message(
                data
            )
        )

        logger.error(
            "API FAILURE | "
            "status=%s | error=%s",
            response.status_code,
            error_message,
        )

        return {
            "success": False,
            "status_code": response.status_code,
            "data": data,
            "error": error_message,
            "request": request_details,
        }

    # -----------------------------------------------------
    # Error extraction
    # -----------------------------------------------------

    @staticmethod
    def _extract_error_message(
        data: Any,
    ) -> str:
        """
        Extract a useful error description from Razorpay's
        response format.
        """

        if not isinstance(
            data,
            dict,
        ):
            return str(data)

        error = data.get(
            "error"
        )

        if isinstance(
            error,
            dict,
        ):
            description = error.get(
                "description"
            )

            if description:
                return str(
                    description
                )

            code = error.get(
                "code"
            )

            if code:
                return str(
                    code
                )

        return str(data)

    # -----------------------------------------------------
    # Connection test
    # -----------------------------------------------------

    def test_connection(
        self,
    ) -> dict:
        """
        Test authenticated access to Razorpay.

        GET /payments?count=1 is used because it is a
        read-only API request and does not create anything.
        """

        return self._request(
            method="GET",
            endpoint="payments?count=1",
        )

    # -----------------------------------------------------
    # Payment Link creation
    # -----------------------------------------------------

    def create_payment_link(
        self,
        amount: float,
        customer_name: str,
        email: str,
        phone: str,
        reference_id: str,
    ) -> dict:
        """
        Create a Razorpay Payment Link.

        Amount is supplied in INR rupees and converted to
        paise for the Razorpay API.

        Example:

            amount=100.00

        becomes:

            amount=10000
        """

        if amount <= 0:
            raise ValueError(
                "Payment amount must be greater than zero."
            )

        if not customer_name:
            raise ValueError(
                "Customer name is required."
            )

        if not email:
            raise ValueError(
                "Customer email is required."
            )

        if not phone:
            raise ValueError(
                "Customer phone is required."
            )

        if not reference_id:
            raise ValueError(
                "Reference ID is required."
            )

        amount_in_paise = int(
            round(
                amount * 100
            )
        )

        payload = {
            "amount": amount_in_paise,
            "currency": "INR",
            "accept_partial": False,
            "description": (
                f"Payment recovery for "
                f"{reference_id}"
            ),
            "customer": {
                "name": customer_name,
                "email": email,
                "contact": phone,
            },
            "reference_id": reference_id,
            "reminder_enable": True,
            "notify": {
                "sms": False,
                "email": False,
            },
        }

        return self._request(
            method="POST",
            endpoint="payment_links",
            payload=payload,
        )


# ---------------------------------------------------------
# Direct connection test
# ---------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print(
        "RAZORPAY TEST MODE CONNECTION TEST"
    )
    print("=" * 60)

    print(
        "Key configured:",
        bool(RAZORPAY_KEY_ID),
    )

    print(
        "Secret configured:",
        bool(RAZORPAY_KEY_SECRET),
    )

    print(
        "Base URL:",
        RAZORPAY_BASE_URL,
    )

    if not RAZORPAY_KEY_ID:
        print()
        print(
            "ERROR: RAZORPAY_KEY_ID is not configured."
        )
        print(
            "Add your Razorpay TEST MODE key to .env."
        )
        raise SystemExit(1)

    if not RAZORPAY_KEY_SECRET:
        print()
        print(
            "ERROR: RAZORPAY_KEY_SECRET is not configured."
        )
        print(
            "Add your Razorpay TEST MODE secret to .env."
        )
        raise SystemExit(1)

    print()
    print(
        "Testing authenticated Razorpay API connection..."
    )
    print()

    client = RazorpayClient()

    result = client.test_connection()

    if result["success"]:
        print(
            "SUCCESS: Razorpay API connection works."
        )

        print(
            f"HTTP status: "
            f"{result['status_code']}"
        )

        print(
            "The project can communicate with "
            "Razorpay TEST MODE."
        )

    else:
        print(
            "FAILED: Razorpay API connection failed."
        )

        print(
            f"HTTP status: "
            f"{result['status_code']}"
        )

        print(
            f"Error: "
            f"{result['error']}"
        )

        print()
        print(
            "Check logs/razorpay_api.log "
            "for the detailed request/response log."
        )

        raise SystemExit(1)