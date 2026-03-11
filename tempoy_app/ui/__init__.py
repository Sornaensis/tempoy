__all__ = ["AllocationPanel", "IssueList", "SettingsDialog"]


def __getattr__(name: str):
	if name == "AllocationPanel":
		from .allocation_panel import AllocationPanel

		return AllocationPanel
	if name == "IssueList":
		from .issue_list import IssueList

		return IssueList
	if name == "SettingsDialog":
		from .settings_dialog import SettingsDialog

		return SettingsDialog
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
