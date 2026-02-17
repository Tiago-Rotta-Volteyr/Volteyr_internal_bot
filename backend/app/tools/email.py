"""
Email tool (MVP: mock send). Human-in-the-loop approval is enforced via interrupt_before in the graph.
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field


class SendEmailInput(BaseModel):
    """Input for send_email tool."""

    recipient: str = Field(description="Email address of the recipient.")
    subject: str = Field(description="Subject of the email.")
    body: str = Field(description="Body content of the email.")


@tool(args_schema=SendEmailInput)
def send_email(recipient: str, subject: str, body: str) -> str:
    """
    Send an email to a recipient. Use this when the user asks to send or write an email.
    In this MVP, the email is not actually sent (no SMTP); it is only logged to the console.
    """
    print(f"FAKE SENDING EMAIL TO {recipient}...")  # noqa: T201
    return f"Email sent successfully to {recipient}"
