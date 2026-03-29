"""
Delete-mails node — real implementation using Gmail API trash.

Flow:
    For each MessageRecord where suggested_action == "delete":
        1. Show email details to the user (sender, subject, date, reasoning)
        2. Prompt: Trash this email? [y/n/q]
           y → trash via Gmail API (or skip if dry_run=True)
           n → skip, add to kept_ids
           q → quit loop, leave remaining messages untouched
    Return updated messages, deleted_ids, kept_ids.
"""

import structlog
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from mail_classifier.models import MessageRecord
from mail_classifier.state import MailClassifierState
from mail_classifier.nodes.read_mails.gmail_authenticate import authenticate

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Gmail service
# ---------------------------------------------------------------------------

def _build_service():
    """Authenticates and returns a Gmail API service client."""
    creds = authenticate()
    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Trash a single message
# ---------------------------------------------------------------------------

def _trash_message(service, message_id: str) -> bool:
    """
    Moves a single message to Gmail Trash via the API.

    Returns True on success, False on failure.
    Trash is recoverable — emails stay in Trash for 30 days before
    Gmail permanently deletes them.
    """
    log = logger.bind(message_id=message_id)
    try:
        log.debug("gmail_trash_started")
        service.users().messages().trash(userId="me", id=message_id).execute()
        log.info("gmail_trash_success")
        return True
    except HttpError as e:
        log.error(
            "gmail_trash_failed",
            status=e.resp.status,
            reason=e._get_reason(),
        )
        return False


# ---------------------------------------------------------------------------
# CLI confirmation prompt
# ---------------------------------------------------------------------------

def _prompt_user(msg: MessageRecord, idx: int, total: int) -> str:
    """
    Displays email details and asks the user for a decision.

    Returns:
        "y" → trash this email
        "n" → skip (keep)
        "q" → quit the confirmation loop entirely
    """
    print(f"\n{'─' * 60}")
    print(f"  Email {idx} of {total}")
    print(f"{'─' * 60}")
    print(f"  From    : {msg.sender or '(unknown)'}")
    print(f"  Subject : {msg.subject or '(no subject)'}")
    print(f"  Date    : {msg.time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  Reason  : {msg.reasoning or '(no reasoning provided)'}")
    print(f"  Confidence : {(msg.confidence or 0) * 100:.0f}%")
    print(f"{'─' * 60}")

    while True:
        raw = input("  Trash this email? [y]es / [n]o / [q]uit : ").strip().lower()
        if raw in ("y", "n", "q"):
            return raw
        print("  Invalid input — please enter y, n, or q.")


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def delete_mails_node(state: MailClassifierState) -> dict:
    """
    LangGraph node: presents delete-candidate emails to the user one by one
    via CLI and trashes confirmed ones via the Gmail API.

    Only messages with suggested_action="delete" are presented.
    Messages marked "keep" or "review" are never touched.

    Respects dry_run=True — shows prompts but skips actual API calls.
    """

    dry_run = state.config.dry_run
    allow_delete = state.config.allow_delete

    # Derive delete candidates from state — single source of truth
    candidates = [
        m for m in state.messages if m.suggested_action == "delete"
    ]

    logger.info(
        "delete_mails_node_started",
        candidates=len(candidates),
        dry_run=dry_run,
        allow_delete=allow_delete,
    )

    if not candidates:
        logger.info(
            "delete_mails_no_candidates",
            hint="No messages with suggested_action='delete' found",
        )
        return {
            "deleted_ids": [],
            "kept_ids": [],
            "status": "completed",
        }

    if not allow_delete:
        logger.warning(
            "delete_mails_skipped",
            reason="allow_delete=False in WorkflowConfig",
            hint="Set allow_delete=True to enable deletions",
        )
        return {
            "kept_ids": [m.id for m in candidates],
            "status": "completed",
        }

    # --- Build Gmail service ---
    try:
        service = _build_service()
        logger.info("gmail_service_ready")
    except Exception as e:
        logger.error("gmail_service_failed", error=str(e))
        return {
            "status": "failed",
            "errors": [f"delete_mails_node failed to authenticate: {str(e)}"],
        }

    # --- CLI confirmation loop ---
    deleted_ids = []
    kept_ids = []
    quit_early = False
    api_errors = []

    print(f"\n{'=' * 60}")
    print(f"  {len(candidates)} email(s) flagged for deletion.")
    if dry_run:
        print("  DRY RUN MODE — no emails will actually be trashed.")
    print(f"{'=' * 60}")

    for idx, msg in enumerate(candidates, 1):

        if quit_early:
            # User quit early — treat remaining as kept
            kept_ids.append(msg.id)
            logger.info(
                "delete_skipped_quit",
                message_id=msg.id,
                subject=msg.subject or "(no subject)",
            )
            continue

        decision = _prompt_user(msg, idx, len(candidates))

        if decision == "q":
            print("\n  Quitting confirmation — remaining emails will be kept.")
            quit_early = True
            kept_ids.append(msg.id)
            logger.info(
                "delete_confirmation_quit",
                at_index=idx,
                remaining=len(candidates) - idx,
            )
            continue

        if decision == "n":
            kept_ids.append(msg.id)
            logger.info(
                "delete_skipped_user",
                message_id=msg.id,
                subject=msg.subject or "(no subject)",
            )
            print("  Kept.")
            continue

        # decision == "y"
        if dry_run:
            logger.info(
                "delete_dry_run",
                message_id=msg.id,
                subject=msg.subject or "(no subject)",
            )
            print("  [DRY RUN] Would not trash this email.")
            deleted_ids.append(msg.id)
        else:
            success = _trash_message(service, msg.id)
            if success:
                deleted_ids.append(msg.id)
                print("  Trashed ✓")
            else:
                # API call failed — treat as kept so the email isn't lost
                kept_ids.append(msg.id)
                api_errors.append(msg.id)
                print("  Failed to trash — keeping for safety.")

    # --- Update MessageRecords to reflect final decisions ---
    updated_messages = []
    deleted_set = set(deleted_ids)
    for msg in state.messages:
        if msg.id in deleted_set:
            updated_messages.append(
                msg.model_copy(update={"deleted": True})
            )
        else:
            updated_messages.append(msg)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print(f"  Done. Trashed: {len(deleted_ids)} | Kept: {len(kept_ids)} | Errors: {len(api_errors)}")
    print(f"{'=' * 60}\n")

    logger.info(
        "delete_mails_node_complete",
        deleted=len(deleted_ids),
        kept=len(kept_ids),
        api_errors=len(api_errors),
        quit_early=quit_early,
        status="completed",
    )

    result = {
        "messages": updated_messages,
        "deleted_ids": deleted_ids,
        "kept_ids": kept_ids,
        "status": "completed",
    }

    if api_errors:
        result["warnings"] = [
            f"Failed to trash message {mid} — kept for safety."
            for mid in api_errors
        ]

    return result