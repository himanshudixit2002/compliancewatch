"""Temporal workflows of the applicability engine. Workflow code is deterministic: it schedules
the activities in ``applicability_engine.application.fanout_activities``, waits on timers and
signals, and combines their results."""

from applicability_engine.workflows.fan_out import FanOutWorkflow

__all__ = ["FanOutWorkflow"]
