from django.db import migrations

_FORWARD = r"""
CREATE FUNCTION catalog_document_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.text, '')), 'B');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER document_search_vector_trigger
BEFORE INSERT OR UPDATE ON catalog_document
FOR EACH ROW EXECUTE FUNCTION catalog_document_search_vector_update();
"""

_REVERSE = r"""
DROP TRIGGER IF EXISTS document_search_vector_trigger ON catalog_document;
DROP FUNCTION IF EXISTS catalog_document_search_vector_update();
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0009_schema_hardening")]
    operations = [migrations.RunSQL(sql=_FORWARD, reverse_sql=_REVERSE)]
