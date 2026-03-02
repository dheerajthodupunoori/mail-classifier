import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from mail_classifier.nodes.read_mails.gmail_authenticate import authenticate
from mail_classifier.nodes.read_mails.models import GmailMessage


def main():
  try:
    creds = authenticate()
    read_messages(datetime.datetime(2026,2, 28, 0, 0, 0), creds)
  except HttpError as error:
    print(f"An error occurred: {error}")


def read_messages(timestamp: datetime.datetime, creds) -> list[dict]:
  """Reads messages from Gmail after a certain timestamp."""
  try:
    # Call the Gmail API
    print("\n" + "="*50)
    print("Starting to fetch messages from Gmail...")
    print("="*50)
    service = build("gmail", "v1", credentials=creds)
    results = (
        service.users()
        .messages()
        .list(userId="me", q=f"after:{int(timestamp.timestamp())}")
        .execute()
    )
    raw_messages = results.get("messages", [])
    print(f"Found {len(raw_messages)} messages after {timestamp}.")

    for idx, message in enumerate(raw_messages, 1):
      print(f"\n--- Processing Message {idx}/{len(raw_messages)} ---")
      # print_message_details(message["id"], creds)
      messages = create_gmail_message_from_mail_message(message["id"], creds)
      print(messages)

    print("\n" + "="*50)
    print("Finished processing all messages")
    print("="*50 + "\n")
    return raw_messages
  except HttpError as error:
    print(f"An error occurred: {error}")
    return []
  
def print_message_details(message_id: str, creds) -> None:
  """Prints the details of a message given its ID."""
  try:
    service = build("gmail", "v1", credentials=creds)
    message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    print(f"  Full Message:")
    import json
    print(json.dumps(message, indent=2))
  except HttpError as error:
    print(f"  Error occurred: {error}")

def create_gmail_message_from_mail_message(message_id: str, creds) -> list[GmailMessage]:
  """Creates a Gmail message object from the raw API response."""
  messages = []
  service = build("gmail", "v1", credentials=creds)
  message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
  
  gmail_message = GmailMessage(
      id=message["id"],
      threadId=message["threadId"],
      labelIds=message.get("labelIds", []),
      snippet=message.get("snippet", ""),
      time=datetime.datetime.fromtimestamp(int(message["internalDate"]) / 1000),
      subject=next((header["value"] for header in message["payload"]["headers"] if header["name"] == "Subject"), ""),
      sender=next((header["value"] for header in message["payload"]["headers"] if header["name"] == "From"), "")
  )
  messages.append(gmail_message)

  return messages

if __name__ == "__main__":
  main()


# python3 -m poetry run python src/mail_classifier/nodes/read_mails/read_mails.py
