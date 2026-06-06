"""Ingest API views: presigned uploads + meeting ingest. Thin wrappers over the
existing IR loaders; all auth via the single bearer token."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.api.auth import BearerTokenAuthentication, HasValidIngestToken
from catalog.api.serializers import UploadRequestSerializer
from catalog.api.uploads import presign_uploads, remote_storage_available


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
