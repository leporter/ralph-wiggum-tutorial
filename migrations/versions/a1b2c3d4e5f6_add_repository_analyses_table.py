"""add repository_analyses table

Adds persistence for successful /learn codebase-analysis results.

Why a dedicated table keyed on (normalized_repo_url, commit_sha):
the learning path is derived from a specific commit's tree, so caching by URL
alone would serve stale guidance after new commits. The unique constraint makes
the (target, commit) pair the cache key, and the normalized-URL index keeps the
lookup that precedes every analysis cheap. Only derived output is stored in
``result_json`` — never raw source.

Chained after f1a2b3c4d5e6 (drop hello table) so ``flask db upgrade`` stays a
reproducible, linear history.

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-06-09 23:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'repository_analyses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('normalized_repo_url', sa.String(length=2048), nullable=False),
        sa.Column('requested_ref', sa.String(length=255), nullable=False),
        sa.Column('scope_path', sa.String(length=2048), nullable=False),
        sa.Column('owner', sa.String(length=255), nullable=False),
        sa.Column('repo', sa.String(length=255), nullable=False),
        sa.Column('default_branch', sa.String(length=255), nullable=False),
        sa.Column('commit_sha', sa.String(length=64), nullable=False),
        sa.Column('result_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'normalized_repo_url', 'commit_sha',
            name='uq_repository_analyses_url_commit',
        ),
    )
    op.create_index(
        'ix_repository_analyses_normalized_repo_url',
        'repository_analyses',
        ['normalized_repo_url'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_repository_analyses_normalized_repo_url',
        table_name='repository_analyses',
    )
    op.drop_table('repository_analyses')
