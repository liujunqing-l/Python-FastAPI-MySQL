"""synchronize identity sequences after legacy explicit-ID inserts

Revision ID: 003_sync_identity_sequences
Revises: 002_heartbeat_records
"""

from alembic import op


revision = "003_sync_identity_sequences"
down_revision = "002_heartbeat_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Earlier development code supplied IDs in application code.  Move each
    # PostgreSQL identity sequence past the current maximum so the new
    # database-generated inserts cannot collide with those rows.
    op.execute(
        """
        DO $$
        DECLARE
            table_name text;
            sequence_name text;
            max_id bigint;
        BEGIN
            FOREACH table_name IN ARRAY ARRAY[
                'devices', 'health_records', 'heartbeat_records',
                'raw_archives', 'ingestion_errors'
            ] LOOP
                sequence_name := pg_get_serial_sequence('public.' || table_name, 'id');
                IF sequence_name IS NOT NULL THEN
                    EXECUTE format('SELECT max(id) FROM public.%I', table_name)
                        INTO max_id;
                    IF max_id IS NULL OR max_id < 1 THEN
                        PERFORM setval(sequence_name, 1, false);
                    ELSE
                        PERFORM setval(sequence_name, max_id + 1, false);
                    END IF;
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # Sequence synchronization is intentionally irreversible metadata repair;
    # there is no safe downgrade operation.
    pass
