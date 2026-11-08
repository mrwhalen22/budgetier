# Moving Budgetier to Qt Widgets

**Done.** All seven steps are in. This page stays as the record of why and how.

Budgetier's window today is a web page: 23 JavaScript files and 5 stylesheets, run in three
different browsers (WebView2 on Windows, WebKit on a Mac, Qt's browser on Linux), talking
to Python through pywebview. This plan replaces that page with a Qt Widgets window written
entirely in Python, using PySide6. Everything below the page stays: importing, PDFs, rules,
the ledger, budgets, bank sync, updates and the Excel export.

## What changes for people using it

- **Same data, same folder.** Nothing on disk changes format, so an update just opens the
  new window on the same data.
- **Faster.** A change updates the window in place. Today every save rewrites the whole page
  and reloads it, about 5 seconds at 50,000 transactions.
- **One look on every system.** Qt draws the same way everywhere, so fixes like the Mac
  first-click workaround go away.
- **Downloads.** These are estimates until the first build:

  | | Today | With Qt Widgets |
  |---|---|---|
  | Windows | 56 MB | about 40–60 MB |
  | Mac, each | 36 MB | about 50–70 MB: Qt replaces the browser macOS provides |
  | Linux | 212–300 MB | about 60–90 MB: no browser inside |

- **Lost on the way:** the look settings and "tour seen" are kept by the browser today, so
  they reset once. They move to `settings.json` in the data folder.

## Decisions to make first

1. **Oldest macOS.** Qt 6.12's Mac package needs **macOS 14 (Sonoma) or newer**. An older Qt
   would reach further back, but it gets fewer fixes. *Recommended: macOS 14, unless your
   Mac customers are on older versions.*
2. **Look.** Either keep today's design (cards, tiles, the Pine, Ocean and Plum palettes,
   light and dark) by generating a Qt style sheet from the same color tokens, or use
   plain native widgets. *Recommended: keep the design. It's more work, but customers
   already know it.*
3. **The command line's HTML report.** `budgetier` on the command line also writes
   `budget.html`, which depends on the page. *Recommended: drop it, and keep the Excel
   workbook it writes too.*
4. **The tour.** *Recommended: keep it, as a short series of highlighted steps.*

## Shape of the new code

```
budgetier/
  views.py         what each tab shows, computed in Python in cents; no Qt
  ui/
    app.py         QApplication, the main window, the sidebar of tabs
    theme.py       color tokens to a Qt style sheet, palettes, light and dark
    widgets.py     tile, card, banner, toast, the busy button
    charts.py      bars, lines and horizontal bars drawn with QPainter, with tooltips
    work.py        runs slow work (sync, PDFs, update checks) off the window's thread
    dialogs/       import review, rule, single change, budget, account, bank, update, confirm
    tabs/          one module per tab
```

- **`views.py` replaces the page's math.** The page computes monthly totals, averages over
  complete months, "this month so far", category totals, budget progress and more in
  JavaScript, with amounts as decimal dollars. These move to Python in cents, so they're
  tested without any window.
- **Charts are drawn by hand.** Today's charts are bars, lines and horizontal bars, about
  135 lines of code. Qt's chart module would add a large download, and drawing these
  with QPainter is about the same amount of code.
- **One thing changes data at a time.** Today a lock makes the page's calls take turns. In
  Qt, everything runs on the window's thread except network calls and reading PDFs. While
  one of those runs, the buttons that change data are disabled, which is how the page
  behaves now.
- **Bank text is always plain text.** Qt labels show HTML when text looks like HTML, so a
  description could add a link or an image. Every label that shows bank text is set to
  plain text, and a test checks that the hostile descriptions from today's page tests
  show as plain text.

## Testing

- `views.py` gets plain unit tests, including the checks the page tests make today:
  this month so far, largest, red means a problem, budgets and savings.
- Until the switch, `tests/test_views_page.py` runs the page's own JavaScript in Chromium
  and checks that `views.py` gets the same numbers for the same period and accounts.
- The window is tested with Qt's own test tools, in the repo's existing `unittest` style. It
  runs with Qt's offscreen display, so it works on Windows locally and on Linux CI with
  no screen and no Xvfb.
- Playwright, the browser downloads and the 40 browser tests go away at the switch. That
  also removes the slow browser install that once timed out CI.
- The self check opens the built app, draws every tab and reports, as it does now, but from
  inside Python instead of through the page.

## Order of work

Each step is one PR, and the current page keeps shipping until the last one. Until then the
new window opens only from the command line, with `python -m budgetier.ui`. The desktop app
doesn't import it, so the installers don't carry Qt until the switch.

1. **Foundation.** PySide6 (Essentials only) for every system, the main window with its tabs,
   the theme, the test setup, and `python -m budgetier.ui`.
2. **`views.py`.** All of the page's math in Python, with tests. The page keeps its own copy
   until the switch.
3. **Read-only tabs.** Overview, Spending, Recurring, Largest, Savings and Help, with the
   charts, and a click on a chart or category opening its transactions.
4. **Transactions and rules.** The transaction list with search, filters and sorting,
   changing one transaction, rules, and the categorize queue.
5. **Accounts.** Adding files and the import review, editing and removing accounts and
   files, the Excel export, the data folder, and bank sync: connect, review, link, sync.
6. **The rest.** Budgets, updates, the look settings, the tour, the keyboard and screen
   readers.
7. **The switch.** The app opens the Qt window. Removed: the page, `report_html.py`,
   pywebview, pythonnet, Playwright and the browser tests. The build spec, self check, CI,
   Linux setup and README are updated, and Mac, Windows and Linux are checked by hand
   before a release.

## Risks

- **Matching the look takes effort.** A Qt style sheet covers colors, borders, spacing and
  fonts, but not everything CSS can do, like some shadows and animations.
- **Screen readers.** Qt Widgets work with Windows and macOS screen readers, but each custom
  widget, such as the charts, needs names and descriptions added by hand.
- **The Mac first click.** It's believed Qt doesn't have the problem pywebview had, but
  that needs checking on a real Mac.
- **Size.** The download estimates above are unmeasured. The 200 MB build limit stays.

## Meanwhile

PR 14, the smaller Linux download, still helps until the switch. If its build can't get under
200 MB, raising that limit to about 230 MB for now is reasonable, since this plan removes the
browser that makes it large.
