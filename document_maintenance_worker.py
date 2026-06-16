"""Compatibility wrapper for the relocated document maintenance worker."""

from .workers.document_maintenance_worker import DocumentKnowledgeMaintenanceWorker

__all__ = ["DocumentKnowledgeMaintenanceWorker"]
