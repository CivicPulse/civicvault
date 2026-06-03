from django.db import migrations

_FORWARD = r"""
CREATE OR REPLACE FUNCTION catalog_segment_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', coalesce(NEW.text, ''));
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS segment_search_vector_trigger ON catalog_transcriptsegment;
CREATE TRIGGER segment_search_vector_trigger
BEFORE INSERT OR UPDATE ON catalog_transcriptsegment
FOR EACH ROW EXECUTE FUNCTION catalog_segment_search_vector_update();
"""

_REVERSE = r"""
DROP TRIGGER IF EXISTS segment_search_vector_trigger ON catalog_transcriptsegment;
DROP FUNCTION IF EXISTS catalog_segment_search_vector_update();
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0011_mediaasset_youtube_unique")]
    operations = [migrations.RunSQL(sql=_FORWARD, reverse_sql=_REVERSE)]
