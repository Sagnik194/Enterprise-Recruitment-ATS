"""Add advanced recruiter job requirements.

Revision ID: b94e2d7a6c31
Revises: 586c2581f586
"""
from alembic import op
import sqlalchemy as sa

revision = 'b94e2d7a6c31'
down_revision = '586c2581f586'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('job_requirements', sa.Column('employment_type', sa.String(30), nullable=True))
    op.add_column('job_requirements', sa.Column('work_mode', sa.String(20), nullable=True))
    op.add_column('job_requirements', sa.Column('department', sa.String(100), nullable=True))
    op.add_column('job_requirements', sa.Column('openings', sa.Integer(), nullable=True))
    op.add_column('job_requirements', sa.Column('maximum_experience_months', sa.Integer(), nullable=True))
    op.add_column('job_requirements', sa.Column('preferred_skills', sa.Text(), nullable=True))
    op.add_column('job_requirements', sa.Column('eligible_degrees', sa.String(255), nullable=True))
    op.add_column('job_requirements', sa.Column('minimum_cgpa', sa.Numeric(4, 2), nullable=True))
    op.add_column('job_requirements', sa.Column('minimum_tenth_percentage', sa.Numeric(5, 2), nullable=True))
    op.add_column('job_requirements', sa.Column('minimum_twelfth_percentage', sa.Numeric(5, 2), nullable=True))
    op.add_column('job_requirements', sa.Column('maximum_active_backlogs', sa.Integer(), nullable=True))
    op.add_column('job_requirements', sa.Column('application_deadline', sa.DateTime(), nullable=True))


def downgrade():
    for name in ('application_deadline','maximum_active_backlogs','minimum_twelfth_percentage',
                 'minimum_tenth_percentage','minimum_cgpa','eligible_degrees','preferred_skills',
                 'maximum_experience_months','openings','department','work_mode','employment_type'):
        op.drop_column('job_requirements', name)
