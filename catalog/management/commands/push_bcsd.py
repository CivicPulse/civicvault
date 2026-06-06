"""Local client: parse a BCSD meeting folder, upload its attachments to R2 via
presigned URLs from the API, then POST the parsed IR to /api/v1/meetings. The
inverse of running ingest_bcsd against a direct DB connection — but it needs no
DB access, only the API token and base URL."""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.api.serializers import payload_from_meeting
from catalog.ingest.bcsd.adapter import parse_meeting_folder


def _post(url, token, payload):
    body = json.dumps(payload, default=str).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 (trusted operator URL)
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _put_file(url, path):
    with open(path, "rb") as fh:
        req = urllib.request.Request(url, data=fh.read(), method="PUT")
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


class Command(BaseCommand):
    help = "Parse a BCSD meeting folder and push it to the remote ingest API."

    def add_arguments(self, parser):
        parser.add_argument("folder")
        parser.add_argument("--api-base", default=os.environ.get("INGEST_API_BASE", ""))
        parser.add_argument("--token", default=os.environ.get("INGEST_API_TOKEN", ""))
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--no-upload", action="store_true")

    def handle(self, *args, **options):
        folder = Path(options["folder"])
        if not folder.is_dir():
            raise CommandError(f"Not a directory: {folder}")
        api_base = options["api_base"].rstrip("/")
        token = options["token"]
        if not api_base or not token:
            raise CommandError("Both --api-base and --token (or their env vars) are required.")

        parsed = parse_meeting_folder(folder)

        if not options["no_upload"]:
            attachments = {
                d.r2_key: d.source_path
                for d in parsed.raw_documents
                if d.is_attachment and d.r2_key and d.source_path
            }
            if attachments:
                status, body = _post(
                    f"{api_base}/api/v1/uploads", token, {"keys": list(attachments)}
                )
                if status != 200:
                    raise CommandError(f"Upload presign failed ({status}): {body}")
                for item in body["uploads"]:
                    put_status = _put_file(item["url"], attachments[item["key"]])
                    if put_status not in (200, 201):
                        raise CommandError(f"Upload PUT failed ({put_status}) for {item['key']}")
                self.stdout.write(
                    f"Uploaded {len(body['uploads'])}, skipped {len(body['skipped'])}."
                )

        payload = payload_from_meeting(parsed)
        if options["force"]:
            payload["force"] = True
        status, body = _post(f"{api_base}/api/v1/meetings", token, payload)
        if status not in (200, 201):
            raise CommandError(f"Meeting POST failed ({status}): {body}")
        self.stdout.write(self.style.SUCCESS(f"Pushed {body.get('source_meeting_id')}: {body}"))
