"""Backend services for SHYFEM UI.

Parsers:
    GrdParser: Parse and generate SHYFEM .grd grid files.
    StrParser: Parse and generate SHYFEM .str simulation parameter files.

Execution:
    ShyfemWrapper: Async subprocess wrapper for SHYFEM CLI tools (shypre, shybas, etc.).
    CommandResult: Return type from ShyfemWrapper with stdout, stderr, return code.
    WorkflowEngine: Multi-step workflow orchestrator for chaining SHYFEM tools.
    WORKFLOW_TEMPLATES: Built-in workflow templates (full simulation, post-process, etc.).

Reporting:
    ReportBuilder: Construct self-contained HTML reports with embedded Plotly charts.
    generate_job_report: Generate a report for a single job execution.
    generate_comparison_report: Generate a side-by-side comparison report for two jobs.
"""

from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.parser_str import StrParser
from shyfem_ui.services.report import ReportBuilder, generate_comparison_report, generate_job_report
from shyfem_ui.services.shyfem_wrapper import CommandResult, ShyfemWrapper
from shyfem_ui.services.workflow import WORKFLOW_TEMPLATES, WorkflowEngine

__all__ = [
    "ShyfemWrapper",
    "CommandResult",
    "StrParser",
    "GrdParser",
    "ReportBuilder",
    "generate_job_report",
    "generate_comparison_report",
    "WorkflowEngine",
    "WORKFLOW_TEMPLATES",
]
