"""Bounded, redacted evidence contract for customer-side browser checks."""
import time
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

STEP_LABELS = {
    'open_app': 'Application opens',
    'login': 'Test account signs in',
    'read_progress': 'Saved learning record is readable',
    'render_notebook': 'Saved word appears in notebook',
    'render_progress': 'Review screen shows saved progress',
}
STEP_IDS = tuple(STEP_LABELS)
MESSAGES = {
    'ok': 'Verified',
    'not_run': 'Skipped after an earlier failure',
    'navigation_failed': 'Application did not become ready',
    'login_failed': 'Login failed or the returned user was not the configured test account',
    'record_missing': 'Expected saved record is missing or does not match the configured fixture',
    'sync_failed': 'Cloud learning data could not be read for this account',
    'notebook_failed': 'Expected saved word was not visible in the notebook',
    'progress_failed': 'Rendered review level did not match the saved learning record',
    'timeout': 'Step did not complete before its timeout',
    'runner_error': 'Browser runner encountered an error',
}


class BusinessStep(BaseModel):
    id: Literal['open_app', 'login', 'read_progress', 'render_notebook', 'render_progress']
    status: Literal['passed', 'failed', 'skipped']
    duration_ms: int = Field(ge=0, le=120000)
    code: Literal['ok', 'not_run', 'navigation_failed', 'login_failed', 'record_missing', 'sync_failed', 'notebook_failed', 'progress_failed', 'timeout', 'runner_error']

    @model_validator(mode='after')
    def consistent(self):
        if self.status == 'passed' and self.code != 'ok':
            raise ValueError('Passed steps require ok')
        if self.status == 'skipped' and self.code != 'not_run':
            raise ValueError('Skipped steps require not_run')
        if self.status == 'failed' and self.code in ('ok', 'not_run'):
            raise ValueError('Failed steps require a failure code')
        return self


class BusinessReceipt(BaseModel):
    run_id: UUID
    workflow: Literal['dutch-learning-v1']
    observed_at: datetime
    steps: list[BusinessStep] = Field(min_length=5, max_length=5)

    @model_validator(mode='after')
    def ordered(self):
        if self.observed_at.tzinfo is None:
            raise ValueError('observed_at must include a timezone')
        if tuple(s.id for s in self.steps) != STEP_IDS:
            raise ValueError('All five workflow steps are required in order')
        failed = False
        for step in self.steps:
            if failed and step.status != 'skipped':
                raise ValueError('Steps following a failure must be skipped')
            if not failed and step.status == 'skipped':
                raise ValueError('A step cannot be skipped before failure')
            failed = failed or step.status == 'failed'
        return self

    def fresh(self):
        age = time.time() - self.observed_at.timestamp()
        return -30 <= age <= 300


def step_evidence(steps):
    return [{**s, 'label': STEP_LABELS[s['id']], 'message': MESSAGES[s['code']]} for s in steps]
