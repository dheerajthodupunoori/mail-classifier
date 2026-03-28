# # python3 -m poetry run python src/mail_classifier/nodes/read_mails/read_mails.py


import base64
import datetime
import structlog
from typing import List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from mail_classifier.nodes.read_mails.gmail_authenticate import authenticate
from mail_classifier.models import MessageRecord

logger = structlog.get_logger(__name__)


def read_messages(
    timestamp: datetime.datetime,
    creds,
    max_messages: Optional[int] = None,
) -> List[MessageRecord]:
    """Reads and parses messages from Gmail after a given timestamp."""

    logger.info(
        "Building Gmail API service client for message fetch."
    )
    service = build("gmail", "v1", credentials=creds)

    # --- Pagination loop ---
    raw_messages = []
    page_token = None
    page_num = 0

    logger.info(
        "Fetching message list from Gmail | since=%s | max_messages=%s",
        timestamp.isoformat(),
        max_messages if max_messages else "unlimited",
    )

    while True:
        page_num += 1
        kwargs = {
            "userId": "me",
            "q": f"after:{int(timestamp.timestamp())}",
        }
        if page_token:
            kwargs["pageToken"] = page_token
        if max_messages:
            kwargs["maxResults"] = min(max_messages - len(raw_messages), 500)

        logger.info(
            "Requesting page %d | query='%s' | pageToken=%s",
            page_num,
            kwargs["q"],
            page_token or "none",
        )

        results = service.users().messages().list(**kwargs).execute()
        page = results.get("messages", [])
        raw_messages.extend(page)

        logger.info(
            "Page %d returned %d message(s) | running total=%d",
            page_num,
            len(page),
            len(raw_messages),
        )

        page_token = results.get("nextPageToken")
        if not page_token:
            logger.info("No nextPageToken — pagination complete.")
            break
        if max_messages and len(raw_messages) >= max_messages:
            logger.info(
                "Reached max_messages limit (%d) — stopping pagination.", max_messages
            )
            break

    raw_messages = raw_messages[:max_messages] if max_messages else raw_messages

    logger.info(
        "Message list fetch complete | total_fetched=%d | pages=%d",
        len(raw_messages),
        page_num,
    )

    if not raw_messages:
        logger.warning(
            "No messages found after %s. "
            "Check the timestamp or Gmail query filter.",
            timestamp.isoformat(),
        )
        return []

    # --- Parse each message ---
    records: List[MessageRecord] = []
    parse_errors = 0

    for idx, message in enumerate(raw_messages, 1):
        message_id = message["id"]
        logger.info(
            "Parsing message %d/%d | id=%s", idx, len(raw_messages), message_id
        )

        record = _parse_message(message_id, service)

        if record:
            records.append(record)
            logger.info(
                "Parsed OK | id=%s | subject='%s' | sender='%s' | time=%s | "
                "body_present=%s | labels=%s",
                record.id,
                record.subject or "(no subject)",
                record.sender or "(unknown sender)",
                record.time.isoformat(),
                record.body_text is not None,
                record.label_ids,
            )
        else:
            parse_errors += 1
            logger.warning(
                "Skipping message %d/%d | id=%s — failed to parse (see error above).",
                idx,
                len(raw_messages),
                message_id,
            )

    logger.info(
        "Parsing complete | parsed_ok=%d | parse_errors=%d | total=%d",
        len(records),
        parse_errors,
        len(raw_messages),
    )

    return records


def _parse_message(message_id: str, service) -> Optional[MessageRecord]:
    """Fetches and parses a single Gmail message into a MessageRecord."""
    try:
        logger.info("Fetching full message payload | id=%s", message_id)
        message = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        headers = message["payload"].get("headers", [])
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
        sender = next((h["value"] for h in headers if h["name"] == "From"), "")

        body_text = _extract_body(message["payload"])
        if body_text is None:
            logger.info(
                "No plain-text body found for message | id=%s | "
                "mimeType=%s — classifier will rely on subject/snippet only.",
                message_id,
                message["payload"].get("mimeType", "unknown"),
            )

        return MessageRecord(
            id=message["id"],
            thread_id=message["threadId"],
            label_ids=message.get("labelIds", []),
            snippet=message.get("snippet", ""),
            time=datetime.datetime.fromtimestamp(
                int(message["internalDate"]) / 1000
            ),
            subject=subject,
            sender=sender,
            body_text=body_text,
        )

    except HttpError as error:
        logger.error(
            "Gmail API error while fetching message | id=%s | status=%s | reason=%s",
            message_id,
            error.resp.status,
            error._get_reason(),
        )
        return None
    except (KeyError, ValueError) as error:
        logger.error(
            "Failed to parse message payload | id=%s | error=%s",
            message_id,
            str(error),
        )
        return None


def _extract_body(payload: dict) -> Optional[str]:
    """Recursively extracts plain-text body from a Gmail message payload."""
    # Single-part message — body is directly on the payload.
    if "parts" not in payload:
        data = payload.get("body", {}).get("data")
        if data:
            logger.info("Extracted body from single-part payload.")
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return None

    # Multi-part message — walk parts looking for text/plain.
    for part in payload["parts"]:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                logger.info("Extracted body from multipart text/plain section.")
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        # Recurse into nested multipart sections (e.g. multipart/alternative).
        if "parts" in part:
            logger.info("Recursing into nested '%s' part.", mime)
            result = _extract_body(part)
            if result:
                return result

    return None


if __name__ == "__main__":
    creds = authenticate()
    records = read_messages(datetime.datetime(2026, 2, 28, 0, 0, 0), creds)
    for r in records:
        logger.info("Record: %s", r)