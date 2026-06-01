from django.contrib import admin

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Motion,
    Organization,
    Person,
    Source,
    Transcript,
    TranscriptSegment,
    Vote,
)


@admin.register(Jurisdiction)
class JurisdictionAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "jurisdiction", "adapter")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "jurisdiction", "reviewed")
    list_filter = ("kind", "reviewed", "jurisdiction")
    search_fields = ("name", "slug")


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("full_name", "slug", "reviewed")
    list_filter = ("reviewed",)
    search_fields = ("full_name", "slug")


class AgendaItemInline(admin.TabularInline):
    model = AgendaItem
    extra = 0


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("date", "kind", "body", "title")
    list_filter = ("kind", "jurisdiction")
    date_hierarchy = "date"
    inlines = [AgendaItemInline]


@admin.register(AgendaItem)
class AgendaItemAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "meeting", "item_type", "outcome_status")
    list_filter = ("item_type", "outcome_status")


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ("kind", "youtube_id", "recorded_on", "duration_seconds")
    list_filter = ("kind", "access_level")


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ("media", "origin", "language", "model")
    list_filter = ("origin", "language")


@admin.register(TranscriptSegment)
class TranscriptSegmentAdmin(admin.ModelAdmin):
    list_display = ("transcript", "start", "end")


@admin.register(MeetingCoverage)
class MeetingCoverageAdmin(admin.ModelAdmin):
    list_display = ("media", "meeting", "start_offset", "end_offset", "split_confirmed")
    list_filter = ("split_confirmed",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "meeting", "ocr_status")
    list_filter = ("kind", "ocr_status", "access_level")
    search_fields = ("title",)


@admin.register(Motion)
class MotionAdmin(admin.ModelAdmin):
    list_display = (
        "agenda_item",
        "kind",
        "sequence",
        "moved_by",
        "seconded_by",
        "status",
        "reviewed",
    )
    list_filter = ("kind", "status", "reviewed")


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("person", "agenda_item", "value", "reviewed")
    list_filter = ("value", "reviewed")


@admin.register(Appearance)
class AppearanceAdmin(admin.ModelAdmin):
    list_display = ("person", "meeting", "role", "reviewed")
    list_filter = ("role", "reviewed")


@admin.register(Citation)
class CitationAdmin(admin.ModelAdmin):
    list_display = ("content_type", "object_id", "document", "page")
    list_filter = ("content_type",)
