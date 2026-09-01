"""Job-level P&L Rollup and Budget Visibility Engine."""

from typing import List, Dict, Any, Optional
from .models import Job, ExtractedInvoice, JobRollup, InvoiceStatus
from .storage import Storage


class RollupEngine:
    @staticmethod
    def compute_job_rollup(job: Job, invoices: List[ExtractedInvoice]) -> JobRollup:
        committed_spend = 0.0
        pending_spend = 0.0
        vendor_breakdown: Dict[str, float] = {}
        cost_code_spent: Dict[str, float] = {}

        for inv in invoices:
            amt = round(inv.total_amount, 2)
            if inv.status == InvoiceStatus.COMMITTED:
                committed_spend += amt
                # Vendor breakdown
                v = inv.vendor_name or "Unknown"
                vendor_breakdown[v] = round(vendor_breakdown.get(v, 0.0) + amt, 2)
                # Cost code breakdown
                code = inv.cost_code or "Uncategorized"
                cost_code_spent[code] = round(cost_code_spent.get(code, 0.0) + amt, 2)
            elif inv.status == InvoiceStatus.PENDING_REVIEW:
                pending_spend += amt

        committed_spend = round(committed_spend, 2)
        pending_spend = round(pending_spend, 2)
        remaining = round(job.budget_total - committed_spend, 2)
        utilization = round((committed_spend / job.budget_total * 100.0), 1) if job.budget_total > 0 else 0.0

        # Cost code breakdown with budgets
        cost_code_breakdown: Dict[str, Dict[str, float]] = {}
        all_codes = set(job.cost_code_budgets.keys()) | set(cost_code_spent.keys())
        for code in sorted(all_codes):
            b_amt = job.cost_code_budgets.get(code, 0.0)
            s_amt = cost_code_spent.get(code, 0.0)
            cost_code_breakdown[code] = {
                "budget": round(b_amt, 2),
                "spent": round(s_amt, 2),
                "remaining": round(b_amt - s_amt, 2),
                "utilization_pct": round((s_amt / b_amt * 100.0), 1) if b_amt > 0 else 0.0,
            }

        return JobRollup(
            job_id=job.id,
            job_name=job.name,
            client_name=job.client_name,
            budget_total=round(job.budget_total, 2),
            committed_spend=committed_spend,
            pending_spend=pending_spend,
            remaining_budget=remaining,
            budget_utilization_pct=utilization,
            invoice_count=len(invoices),
            vendor_breakdown=vendor_breakdown,
            cost_code_breakdown=cost_code_breakdown,
        )

    @classmethod
    def compute_all_rollups(cls, storage: Storage) -> Dict[str, Any]:
        jobs = storage.list_jobs()
        all_invoices = storage.list_invoices()

        rollups = []
        total_budget = 0.0
        total_committed = 0.0
        total_pending = 0.0

        for job in jobs:
            job_invs = [i for i in all_invoices if i.job_name == job.name]
            r = cls.compute_job_rollup(job, job_invs)
            rollups.append(r)
            total_budget += r.budget_total
            total_committed += r.committed_spend
            total_pending += r.pending_spend

        return {
            "jobs": rollups,
            "company_summary": {
                "total_budget": round(total_budget, 2),
                "total_committed_spend": round(total_committed, 2),
                "total_pending_spend": round(total_pending, 2),
                "total_remaining_budget": round(total_budget - total_committed, 2),
                "active_jobs_count": len(jobs),
                "total_invoices_count": len(all_invoices),
            }
        }
