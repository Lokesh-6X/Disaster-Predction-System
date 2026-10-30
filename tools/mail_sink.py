"""Local test mail server: accepts alert emails and saves them instead of delivering.

Run (from the project root), then set SMTP_HOST=localhost, SMTP_PORT=1025 and
SMTP_STARTTLS=false in .env:

    .venv\\Scripts\\python.exe tools\\mail_sink.py

Each email is printed and saved to logs\\mail\\<time>_<n>.eml (open it with
Outlook or any mail program, or read it as text).
"""

import argparse
import sys
import time
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from pathlib import Path

from aiosmtpd.controller import Controller

MAIL_DIR = Path(__file__).resolve().parents[1] / "logs" / "mail"


class SaveHandler:
    def __init__(self) -> None:
        self.count = 0

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 (aiosmtpd API)
        self.count += 1
        MAIL_DIR.mkdir(parents=True, exist_ok=True)
        path = MAIL_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{self.count}.eml"
        path.write_bytes(envelope.content)
        subject = str(make_header(decode_header(message_from_bytes(envelope.content)["Subject"])))
        print(f"{datetime.now():%H:%M:%S}  to {', '.join(envelope.rcpt_tos)}  {subject}")
        print(f"          saved {path}")
        return "250 Message accepted"


def main() -> None:
    parser = argparse.ArgumentParser(description="Local SMTP server that saves emails to files.")
    parser.add_argument("--port", type=int, default=1025)
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    controller = Controller(SaveHandler(), hostname="127.0.0.1", port=args.port)
    controller.start()
    print(f"Test mail server on localhost:{args.port}; saving to {MAIL_DIR} (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.stop()


if __name__ == "__main__":
    main()
