"""Backend services for SHYFEM UI."""

from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.parser_str import StrParser
from shyfem_ui.services.report import ReportBuilder, generate_job_report
from shyfem_ui.services.shyfem_wrapper import CommandResult, ShyfemWrapper

__all__ = [
    "ShyfemWrapper",
    "CommandResult",
    "StrParser",
    "GrdParser",
    "ReportBuilder",
    "generate_job_report",
]
