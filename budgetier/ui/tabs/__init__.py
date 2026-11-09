"""One module per tab. Each build(ctx) returns the tab's contents for the window to show."""
from . import (
            accounts,
            budgets,
            help,
            investments,
            overview,
            recurring,
            rules,
            savings,
            spending,
            transactions,
            year,
)

BUILDERS = {"Overview": overview.build, "Spending": spending.build, "Recurring": recurring.build,
            "Savings": savings.build, "Investments": investments.build, "Year in review": year.build,
            "Transactions": transactions.build, "Rules": rules.build, "Accounts": accounts.build,
            "Budgets": budgets.build, "Help": help.build}
