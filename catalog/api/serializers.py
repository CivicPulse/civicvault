"""DRF serializers mirroring the ingest IR (catalog/ingest/ir.py). They validate
inbound JSON and rebuild the frozen IR dataclasses via `to_ir()`. The IR is the
published API contract; field types are chosen for exact round-trip (Decimal,
date, time). `payload_from_meeting` does the inverse (dataclass → JSON-safe dict)
for the local push client and tests."""

import dataclasses

from rest_framework import serializers

from catalog.ingest import ir


class PersonSerializer(serializers.Serializer):
    full_name = serializers.CharField()
    raw_name = serializers.CharField()
    role_hint = serializers.CharField(required=False, allow_blank=True, default="")


class VoteSerializer(serializers.Serializer):
    person = PersonSerializer()
    value = serializers.CharField()


class MotionSerializer(serializers.Serializer):
    kind = serializers.CharField()
    sequence = serializers.IntegerField()
    moved_by = PersonSerializer(required=False, allow_null=True)
    seconded_by = PersonSerializer(required=False, allow_null=True)
    result_text = serializers.CharField(allow_blank=True)
    status = serializers.CharField()


class AppearanceSerializer(serializers.Serializer):
    person = PersonSerializer()
    role = serializers.CharField()


class AgendaItemSerializer(serializers.Serializer):
    order = serializers.IntegerField()
    code = serializers.CharField(allow_blank=True)
    title = serializers.CharField(allow_blank=True)
    item_type = serializers.CharField()
    reading_stage = serializers.CharField(allow_blank=True)
    section = serializers.CharField(allow_blank=True)
    outcome_text = serializers.CharField(required=False, allow_blank=True, default="")
    outcome_status = serializers.CharField(required=False, default="none")
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True, default=None
    )
    amount_text = serializers.CharField(required=False, allow_blank=True, default="")
    motions = MotionSerializer(many=True, required=False, default=list)
    votes = VoteSerializer(many=True, required=False, default=list)
    file_names = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class DocumentSerializer(serializers.Serializer):
    kind = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    source_path = serializers.CharField(allow_blank=True)
    text = serializers.CharField(allow_blank=True)
    r2_key = serializers.CharField(required=False, allow_blank=True, default="")
    ocr_status = serializers.CharField(required=False, default="unknown")
    agenda_item_code = serializers.CharField(required=False, allow_null=True, default=None)
    is_attachment = serializers.BooleanField(required=False, default=False)


class MeetingSerializer(serializers.Serializer):
    date = serializers.DateField()
    start_time = serializers.TimeField(required=False, allow_null=True, default=None)
    kind_slug = serializers.CharField()
    source_meeting_id = serializers.CharField()
    source_url = serializers.CharField(allow_blank=True)
    source_path = serializers.CharField(allow_blank=True)
    folder_name = serializers.CharField(allow_blank=True)
    title = serializers.CharField(allow_blank=True)
    roster = PersonSerializer(many=True, required=False, default=list)
    agenda_items = AgendaItemSerializer(many=True, required=False, default=list)
    appearances = AppearanceSerializer(many=True, required=False, default=list)
    has_minutes = serializers.BooleanField(required=False, default=False)
    raw_documents = DocumentSerializer(many=True, required=False, default=list)

    def to_ir(self) -> ir.ParsedMeeting:
        d = self.validated_data
        return ir.ParsedMeeting(
            date=d["date"],
            start_time=d["start_time"],
            kind_slug=d["kind_slug"],
            source_meeting_id=d["source_meeting_id"],
            source_url=d["source_url"],
            source_path=d["source_path"],
            folder_name=d["folder_name"],
            title=d["title"],
            roster=tuple(_person(p) for p in d["roster"]),
            agenda_items=tuple(_agenda_item(a) for a in d["agenda_items"]),
            appearances=tuple(_appearance(a) for a in d["appearances"]),
            has_minutes=d["has_minutes"],
            raw_documents=tuple(_document(x) for x in d["raw_documents"]),
        )


def _person(d) -> ir.ParsedPerson:
    return ir.ParsedPerson(
        full_name=d["full_name"], raw_name=d["raw_name"], role_hint=d.get("role_hint", "")
    )


def _opt_person(d):
    return _person(d) if d else None


def _vote(d) -> ir.ParsedVote:
    return ir.ParsedVote(person=_person(d["person"]), value=d["value"])


def _motion(d) -> ir.ParsedMotion:
    return ir.ParsedMotion(
        kind=d["kind"],
        sequence=d["sequence"],
        moved_by=_opt_person(d.get("moved_by")),
        seconded_by=_opt_person(d.get("seconded_by")),
        result_text=d["result_text"],
        status=d["status"],
    )


def _appearance(d) -> ir.ParsedAppearance:
    return ir.ParsedAppearance(person=_person(d["person"]), role=d["role"])


def _agenda_item(d) -> ir.ParsedAgendaItem:
    return ir.ParsedAgendaItem(
        order=d["order"],
        code=d["code"],
        title=d["title"],
        item_type=d["item_type"],
        reading_stage=d["reading_stage"],
        section=d["section"],
        outcome_text=d.get("outcome_text", ""),
        outcome_status=d.get("outcome_status", "none"),
        amount=d.get("amount"),
        amount_text=d.get("amount_text", ""),
        motions=tuple(_motion(m) for m in d.get("motions", [])),
        votes=tuple(_vote(v) for v in d.get("votes", [])),
        file_names=tuple(d.get("file_names", [])),
    )


def _document(d) -> ir.ParsedDocument:
    return ir.ParsedDocument(
        kind=d["kind"],
        title=d["title"],
        source_path=d["source_path"],
        text=d["text"],
        r2_key=d.get("r2_key", ""),
        ocr_status=d.get("ocr_status", "unknown"),
        agenda_item_code=d.get("agenda_item_code"),
        is_attachment=d.get("is_attachment", False),
    )


def payload_from_meeting(parsed: ir.ParsedMeeting) -> dict:
    """Dataclass → plain dict (tuples become lists). JSON-encode with
    `json.dumps(..., default=str)` so Decimal/date/time serialize as strings the
    serializers parse back exactly."""
    return dataclasses.asdict(parsed)
