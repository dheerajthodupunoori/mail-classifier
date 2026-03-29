"""LangGraph workflow graph for the mail-classifier pipeline."""

from dotenv import load_dotenv
load_dotenv()

import structlog

from langgraph.graph import StateGraph, END

from mail_classifier.state import MailClassifierState, make_initial_state
from mail_classifier.models import WorkflowConfig
from mail_classifier.nodes.read_mails.node import read_mails_node
from mail_classifier.nodes.classify_mail.node import classify_mails_node
from mail_classifier.nodes.delete_mail.node import delete_mails_node

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Routing functions (conditional edges)
# ---------------------------------------------------------------------------

def route_after_read(state: MailClassifierState) -> str:
    """After read_mails_node: abort on failure, continue if messages were fetched."""
    if state.status == "failed":
        logger.warning(
            "Routing to END after read_mails_node — status=failed | errors=%s",
            state.errors,
        )
        return "end"

    if not state.messages:
        logger.info(
            "Routing to END after read_mails_node — no messages fetched."
        )
        return "end"

    logger.info(
        "Routing to classify_mails_node | messages=%d", len(state.messages)
    )
    return "classify"


def route_after_classify(state: MailClassifierState) -> str:
    """After classify_mails_node: skip delete if no candidates or deletion disabled."""
    if state.status == "failed":
        logger.warning(
            "Routing to END after classify_mails_node — status=failed | errors=%s",
            state.errors,
        )
        return "end"

    if not state.config.allow_delete:
        logger.info(
            "Routing to END — allow_delete=False in WorkflowConfig. "
            "No deletions will be performed."
        )
        return "end"

    delete_candidates = [
        m for m in state.messages if m.suggested_action == "delete"
    ]
    if not delete_candidates:
        logger.info(
            "Routing to END — no messages with suggested_action='delete'."
        )
        return "end"

    logger.info(
        "Routing to delete_mails_node | candidates=%d", len(delete_candidates)
    )
    return "delete"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Constructs and compiles the mail-classifier LangGraph workflow."""

    logger.info("Building mail-classifier LangGraph workflow.")

    graph = StateGraph(MailClassifierState)

    # Register nodes
    graph.add_node("read_mails", read_mails_node)
    graph.add_node("classify_mails", classify_mails_node)
    graph.add_node("delete_mails", delete_mails_node)

    # Entry point
    graph.set_entry_point("read_mails")

    # Conditional edge: read → classify or end
    graph.add_conditional_edges(
        "read_mails",
        route_after_read,
        {
            "classify": "classify_mails",
            "end": END,
        },
    )

    # Conditional edge: classify → delete or end
    graph.add_conditional_edges(
        "classify_mails",
        route_after_classify,
        {
            "delete": "delete_mails",
            "end": END,
        },
    )

    # Delete always leads to end
    graph.add_edge("delete_mails", END)

    compiled = graph.compile()
    logger.info("Workflow graph compiled successfully.")
    return compiled


# ---------------------------------------------------------------------------
# Entrypoint for local testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import datetime

    config = WorkflowConfig(
        since_timestamp=datetime.datetime(2026, 2, 28, 0, 0, 0),
        allow_delete=True,   # Set True to test delete node routing
        dry_run=True,
        max_messages=10,      # Keep small for testing
    )

    initial_state = make_initial_state(config)
    workflow = build_graph()

    logger.info("Invoking workflow with config: %s", config)
    final_state = workflow.invoke(initial_state)

    print(workflow.get_graph().draw_ascii())

    logger.info("=== Workflow Complete ===")
    logger.info("Status        : %s", final_state["status"])
    logger.info("Fetched       : %d", final_state["fetched_count"])
    logger.info("Classified    : %d", final_state["classified_count"])
    logger.info("Deleted       : %s", final_state["deleted_ids"])
    logger.info("Errors        : %s", final_state["errors"])
    logger.info("Warnings      : %s", final_state["warnings"])