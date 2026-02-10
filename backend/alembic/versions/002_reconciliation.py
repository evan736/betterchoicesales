"""Add reconciliation columns to statement tables

Revision ID: 002_reconciliation
Revises: None
Create Date: 2026-02-10
"""
from alembic import op
import sqlalchemy as sa

revision = '002_reconciliation'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to statement_imports
    op.execute("""
        DO $$
        BEGIN
            -- statement_imports: add total_premium, total_commission if missing
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_imports' AND column_name='total_premium'
            ) THEN
                ALTER TABLE statement_imports ADD COLUMN total_premium NUMERIC(12,2) DEFAULT 0;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_imports' AND column_name='total_commission'
            ) THEN
                ALTER TABLE statement_imports ADD COLUMN total_commission NUMERIC(12,2) DEFAULT 0;
            END IF;

            -- statement_lines: add new columns
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='insured_name'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN insured_name VARCHAR;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='transaction_type_raw'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN transaction_type_raw VARCHAR;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='effective_date'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN effective_date TIMESTAMPTZ;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='commission_rate'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN commission_rate NUMERIC(5,4);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='producer_name'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN producer_name VARCHAR;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='product_type'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN product_type VARCHAR;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='line_of_business'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN line_of_business VARCHAR;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='state'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN state VARCHAR(2);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='term_months'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN term_months INTEGER;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='match_confidence'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN match_confidence VARCHAR;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='assigned_agent_id'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN assigned_agent_id INTEGER REFERENCES users(id);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='agent_commission_amount'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN agent_commission_amount NUMERIC(12,2);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='statement_lines' AND column_name='agent_commission_rate'
            ) THEN
                ALTER TABLE statement_lines ADD COLUMN agent_commission_rate NUMERIC(5,4);
            END IF;

        END $$;
    """)

    # Update carrier type enum if needed (add grange etc)
    op.execute("""
        DO $$
        BEGIN
            -- Add new carrier types to enum
            IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'grange' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'carriertype')) THEN
                ALTER TYPE carriertype ADD VALUE IF NOT EXISTS 'grange';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'safeco' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'carriertype')) THEN
                ALTER TYPE carriertype ADD VALUE IF NOT EXISTS 'safeco';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'travelers' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'carriertype')) THEN
                ALTER TYPE carriertype ADD VALUE IF NOT EXISTS 'travelers';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'hartford' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'carriertype')) THEN
                ALTER TYPE carriertype ADD VALUE IF NOT EXISTS 'hartford';
            END IF;
        EXCEPTION WHEN others THEN
            NULL;
        END $$;
    """)

    # Add transaction_type enum if needed
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transactiontype') THEN
                CREATE TYPE transactiontype AS ENUM (
                    'new_business', 'renewal', 'endorsement', 'cancellation',
                    'reinstatement', 'audit', 'adjustment', 'other'
                );
            END IF;
        EXCEPTION WHEN others THEN
            NULL;
        END $$;
    """)

    # Add new status values
    op.execute("""
        DO $$
        BEGIN
            ALTER TYPE statementstatus ADD VALUE IF NOT EXISTS 'processed';
            ALTER TYPE statementstatus ADD VALUE IF NOT EXISTS 'reconciled';
            ALTER TYPE statementstatus ADD VALUE IF NOT EXISTS 'approved';
        EXCEPTION WHEN others THEN
            NULL;
        END $$;
    """)

    # Add ForeignKey from statement_lines to statement_imports if missing
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'statement_lines_statement_import_id_fkey'
            ) THEN
                BEGIN
                    ALTER TABLE statement_lines
                    ADD CONSTRAINT statement_lines_statement_import_id_fkey
                    FOREIGN KEY (statement_import_id) REFERENCES statement_imports(id);
                EXCEPTION WHEN others THEN NULL;
                END;
            END IF;
        END $$;
    """)


def downgrade():
    pass
