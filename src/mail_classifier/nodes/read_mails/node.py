"""Entrypoint for the Gmail read node."""

from mail_classifier.nodes.read_mails.read_mails import main


def read_mails_node():
  """Node to read mails from Gmail."""
  main()


if __name__ == "__main__":
  read_mails_node()

# poetry run python src/mail_classifier/nodes/read_mails/node.py
