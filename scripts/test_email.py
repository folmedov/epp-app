"""Test SMTP connectivity by sending a test email.

Usage:
    PYTHONPATH=. python scripts/test_email.py --to recipient@example.com
    PYTHONPATH=. python scripts/test_email.py --to recipient@example.com \\
          --subject "Test" --message "Hello" --dry-run

Exit codes:
    0   Email sent successfully (or dry-run would send).
    1   SMTP configuration incomplete or connection failed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.notifications.email import (
    NotificationError,
    check_smtp_config,
    _build_message,
    _send,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)


async def run(to_email: str, subject: str, message: str, dry_run: bool) -> None:
    try:
        check_smtp_config()
    except NotificationError as exc:
        LOGGER.error("SMTP configuration error: %s", exc)
        sys.exit(1)

    msg = _build_message(
        to_email=to_email,
        subject=subject,
        html_body=f"<p>{message}</p>",
        plain_body=message,
    )

    if dry_run:
        LOGGER.info("[dry-run] Would send test email to %s", to_email)
        LOGGER.info("  Subject: %s", subject)
        LOGGER.info("  Body: %s", message)
        return

    try:
        await _send(msg)
        LOGGER.info("Test email sent successfully to %s", to_email)
    except NotificationError as exc:
        LOGGER.error("SMTP send failed: %s", exc)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test SMTP configuration by sending a test email.",
    )
    parser.add_argument(
        "--to",
        dest="to_email",
        default=None,
        help="Recipient email address.",
    )
    parser.add_argument(
        "--subject",
        default="Test email from Job Tracker",
        help="Email subject line.",
    )
    parser.add_argument(
        "--message",
        default="This is a test email to verify SMTP configuration.",
        help="Email body text.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check configuration but do not send.",
    )
    args = parser.parse_args()

    if not args.to_email:
        parser.print_help()
        sys.exit(1)

    asyncio.run(run(args.to_email, args.subject, args.message, args.dry_run))


if __name__ == "__main__":
    main()
