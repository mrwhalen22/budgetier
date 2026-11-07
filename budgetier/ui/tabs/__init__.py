"""One module per tab. Each build(ctx) returns the tab's contents for the window to show."""
from . import help, largest, overview, recurring, savings, spending

BUILDERS = {"Overview": overview.build, "Spending": spending.build, "Recurring": recurring.build,
            "Largest": largest.build, "Savings": savings.build, "Help": help.build}
