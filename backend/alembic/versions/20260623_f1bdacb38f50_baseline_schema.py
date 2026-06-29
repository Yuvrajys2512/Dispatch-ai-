"""baseline schema

Revision ID: f1bdacb38f50
Revises: 
Create Date: 2026-06-23 23:31:50.505065
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1bdacb38f50'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('callers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=False),
    sa.Column('display_name', sa.String(length=128), nullable=True),
    sa.Column('total_calls', sa.Integer(), server_default='0', nullable=False),
    sa.Column('calls_today', sa.Integer(), server_default='0', nullable=False),
    sa.Column('is_blacklisted', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('flagged_prank', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('first_seen', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_callers'))
    )
    with op.batch_alter_table('callers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_callers_phone'), ['phone'], unique=True)

    op.create_table('calls',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('caller_id', sa.Uuid(), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=False),
    sa.Column('state', sa.Enum('GREETING', 'INCIDENT_TYPE', 'LOCATION', 'DETAILS', 'SEVERITY_SCORE', 'ROUTE', 'ROUTED', 'HANDED_OVER', 'RESOLVED', 'ABANDONED', name='callstate', native_enum=False, length=32), nullable=False),
    sa.Column('caller_name', sa.String(length=128), nullable=True),
    sa.Column('location_text', sa.Text(), nullable=True),
    sa.Column('location_lat', sa.Float(), nullable=True),
    sa.Column('location_lng', sa.Float(), nullable=True),
    sa.Column('incident_type', sa.Enum('ACCIDENT', 'ASSAULT', 'THEFT', 'FIRE', 'MEDICAL', 'DOMESTIC', 'OTHER', 'UNKNOWN', name='incidenttype', native_enum=False, length=32), nullable=False),
    sa.Column('people_involved', sa.Integer(), nullable=True),
    sa.Column('severity', sa.Enum('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'JUNK', name='severity', native_enum=False, length=32), nullable=False),
    sa.Column('confidence', sa.Float(), server_default='0', nullable=False),
    sa.Column('needs_ambulance', sa.Boolean(), nullable=False),
    sa.Column('needs_police', sa.Boolean(), nullable=False),
    sa.Column('needs_fire', sa.Boolean(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('route_target', sa.Enum('OPERATOR_IMMEDIATE', 'OPERATOR_QUEUE', 'AI_RESOLVE', 'AUTO_RESOLVE', name='routetarget', native_enum=False, length=32), nullable=True),
    sa.Column('route_reason', sa.Text(), nullable=True),
    sa.Column('handoff', sa.Boolean(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['caller_id'], ['callers.id'], name=op.f('fk_calls_caller_id_callers'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_calls'))
    )
    with op.batch_alter_table('calls', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_calls_caller_id'), ['caller_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_calls_phone'), ['phone'], unique=False)

    op.create_table('events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('call_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['call_id'], ['calls.id'], name=op.f('fk_events_call_id_calls'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_events'))
    )
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_events_call_id'), ['call_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_kind'), ['kind'], unique=False)

    op.create_table('transcript_turns',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('call_id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('speaker', sa.Enum('CALLER', 'AI', 'OPERATOR', name='speaker', native_enum=False, length=32), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('is_final', sa.Boolean(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['call_id'], ['calls.id'], name=op.f('fk_transcript_turns_call_id_calls'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transcript_turns'))
    )
    with op.batch_alter_table('transcript_turns', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_transcript_turns_call_id'), ['call_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('transcript_turns', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_transcript_turns_call_id'))

    op.drop_table('transcript_turns')
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_events_kind'))
        batch_op.drop_index(batch_op.f('ix_events_call_id'))

    op.drop_table('events')
    with op.batch_alter_table('calls', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_calls_phone'))
        batch_op.drop_index(batch_op.f('ix_calls_caller_id'))

    op.drop_table('calls')
    with op.batch_alter_table('callers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_callers_phone'))

    op.drop_table('callers')
