"""One module per tab. Each build(ctx) returns the tab's contents for the window to show."""
from . import accounts, help, largest, overview, recurring, rules, savings, spending, transactions

BUILDERS = {"Overview": overview.build, "Spending": spending.build, "Recurring": recurring.build,
            "Largest": largest.build, "Savings": savings.build, "Transactions": transactions.build,
            "Rules": rules.build, "Accounts": accounts.build, "Help": help.build}
