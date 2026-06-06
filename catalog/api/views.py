"""Ingest API views: presigned uploads + meeting ingest. Thin wrappers over the
existing IR loaders; all auth via the single bearer token."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.api.auth import BearerTokenAuthentication, HasValidIngestToken
from catalog.api.serializers import MeetingSerializer, UploadRequestSerializer
from catalog.api.services import bcsd_context, meeting_has_reviewed_facts
from catalog.api.uploads import presign_uploads, remote_storage_available
from catalog.ingest.loader import load_meeting
from catalog.models import Vote


class UploadsView(APIView):
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [HasValidIngestToken]

    def post(self, request):
        if not remote_storage_available():
            return Response(
                {"detail": "No remote storage configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        serializer = UploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(presign_uploads(serializer.validated_data["keys"]))


class MeetingsView(APIView):
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [HasValidIngestToken]

    def post(self, request):
        force = bool(request.data.get("force", False))
        serializer = MeetingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parsed = serializer.to_ir()

        jurisdiction, source, body = bcsd_context()
        # The guard and load_meeting are separate DB operations (not one
        # transaction); acceptable for this single-operator ingest tool.
        if not force and meeting_has_reviewed_facts(source, parsed.source_meeting_id):
            return Response(
                {
                    "detail": (
                        f"Meeting {parsed.source_meeting_id} has reviewed facts; "
                        f"pass force=true to overwrite."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            meeting = load_meeting(parsed, source=source, jurisdiction=jurisdiction, body=body)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_summary(parsed, meeting), status=status.HTTP_201_CREATED)


def _summary(parsed, meeting) -> dict:
    attachments = sum(1 for d in parsed.raw_documents if d.is_attachment)
    return {
        "slug": meeting.slug,
        "source_meeting_id": meeting.source_meeting_id,
        "agenda_items": meeting.agenda_items.count(),
        # Single aggregate count (avoids per-item N+1).
        "votes": Vote.objects.filter(agenda_item__meeting=meeting).count(),
        "appearances": meeting.appearances.count(),
        "attachments": attachments,
        # The loader always writes reviewed=False proposals.
        "reviewed": False,
    }
