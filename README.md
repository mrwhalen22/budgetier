# Budgetier

Merges CSV exports from your banks and cards into one continuous history per
account, then shows your monthly spending, recurring payments, largest expenses
and savings. Everything runs on this machine, and your data stays here unless you turn on
[bank sync](#bank-sync). The only other request it makes is asking GitHub for the latest
version when it opens; see [Updates](#updates).

## Use it

Download the installer for your system from the [latest release](../../releases/latest).

**Windows:** run `Budgetier-Windows.exe` and approve the admin prompt. It installs for everyone
on the PC, with your choice of location and shortcuts, and appears in Windows' Installed
Apps, where you can uninstall it. The installer isn't code signed, so Windows may warn you the first time; choose
**More info**, then **Run anyway**. Then open **Budgetier** from the Start menu or desktop.

**Linux:** download `Budgetier-Linux.tar.gz`, unpack it wherever you like, and run
`Budgetier/Budgetier`. It's for 64-bit Intel or AMD systems as new as Ubuntu 22.04 or so. To
uninstall, delete the folder. It doesn't add itself to your applications menu, and bank sync
needs a keyring service such as GNOME Keyring.

**macOS:** choose `Budgetier-macOS-Apple-Silicon.dmg` for an M-series Mac, or `Budgetier-macOS-Intel.dmg`
for an Intel one. Apple menu > **About This Mac** shows which you have. It needs macOS 14
(Sonoma) or newer. Open the file and
drag **Budgetier** onto **Applications**. To uninstall, move it from Applications to the
Trash. The app isn't signed by Apple, so macOS blocks it the first time:

1. Open **Budgetier** from Applications and dismiss the warning.
2. Open **System Settings** > **Privacy & Security**, scroll down, and choose **Open Anyway**.
3. Confirm with your password. After that it opens normally.

- **Add files** opens a file picker for CSV exports and Synchrony PDFs. Date ranges can
  overlap. You review each file before anything is saved, and your original files stay
  where they are.
- **Rules** lists merchants that need a category. Choose **Categorize** and work down the
  list with **Save and next**, or select any row on the Transactions tab to give it a name
  and category. Rules apply to all your history and to future imports. To change one
  transaction and nothing else, select its row and choose **Just this transaction**.
  To give one transaction several categories, like a Costco trip that was part groceries
  and part household, choose **Split** and give each part an amount; they need to add up
  to the whole.
- **Budgets** sets a monthly target for a category, as a dollar amount or a percent of
  income, and shows what's left. A percent target follows each month's income. While a
  month is still in progress it uses the average of the last 3 complete months instead,
  because your pay may not have landed yet.
- **Savings goals**, also on the Budgets tab, track saving toward something: an emergency
  fund, a trip, next year's car insurance. Keep a goal in a savings or investing account, so
  its balance is the progress, or in an amount you update yourself. Give it a date and it
  shows what a month gets it there, and whether you're on track from where it started.
- **Recurring** lists bills, subscriptions and regular income, and what's coming up over
  the next 30 days: each bill and paycheck on its usual day, and card and loan payments
  guessed from recent ones. With a checking balance set, it shows what they'd do to
  checking and its lowest point, and the Overview warns when bills would take checking
  below zero before payday.
- **Accounts** is where you edit an account, set a balance, remove one imported file or
  a whole account, export the Excel workbook, and open the data folder.
- **Help** shows which banks work, tips for accurate numbers, the keyboard shortcuts, and a
  short tour.

Removing a file rebuilds that account from its other files, so transactions another
file also covers stay.

Before bringing in your own accounts, **Try it with sample data** on the welcome screen shows
a year and a half of made-up accounts to look around. It's kept in a folder of its own and
thrown away when you choose **Leave sample data** or close Budgetier; adding files and bank
sync wait until you've left it.

**Export CSV** on the Transactions tab saves every transaction it lists, with your search,
filters and period applied, for a spreadsheet or another app.

On the Overview, Spending and Savings charts, select a month, or press Enter on it, to show
just that month.

After new transactions arrive, the Overview lists what's new since you last looked: how
many came in and what they add up to, payments newly found to recur, and bills whose price
changed. **Got it** clears it, as does closing Budgetier after seeing the Overview.

When the numbers are a while out of date, the Overview says so with a button to fix it:
after a week without a bank sync, or when your newest transaction is over a month old.

A change to a category, a rule, a budget or an account's details can be undone: choose
**Undo** in the note that appears, or press Ctrl+Z. Removing a file or an account asks
first instead, since it rebuilds the account.

Budgetier opens where you left it: the same size and place, tab, period and accounts. After
a change it works out the new numbers in the background, so on a long history you can keep
reading while **Updating...** shows beside the tab's title.

| Keys | Does |
| --- | --- |
| Ctrl+1 to Ctrl+9 | Show the first nine tabs, in the sidebar's order |
| Ctrl+F | Find a transaction |
| Ctrl+Z | Undo the last change |
| Ctrl+I | Add files |
| Ctrl+R | Sync banks |
| Ctrl+, | Appearance |
| F1 | Help |

On a Mac, use Command in place of Ctrl.

## Updates

When the installed app opens, it asks GitHub for the latest release. No financial data goes
with that request, and being offline is fine. If there's a newer version, **Update to x.y.z**
appears in the sidebar. Nothing downloads until you choose it, and the download must match the
release's `SHA256SUMS.txt`.

- **Windows:** Budgetier closes, Windows asks for permission, and it opens again when it's done.
- **macOS:** the download opens, and you drag Budgetier to Applications to replace the old copy.
- **Linux:** the download opens, and you unpack it over your Budgetier folder.

Your data is kept apart from the program, so updating doesn't touch it. To stop the automatic
check, or to check by hand, use the buttons at the bottom of the Help tab.

## Appearance

Choose **Appearance** at the bottom of the sidebar to pick a theme (Pine, Ocean or Plum) and
light, dark or matching your system. **Text size** makes all the text smaller or larger, up to
about a third bigger. **Reduce motion** turns off the short fades, slides and
growing bars. The choice is kept in your data folder.

## Where things live

| What | Where |
| --- | --- |
| The program on Windows | `C:\Program Files\Budgetier` |
| Your data on Windows | `%LOCALAPPDATA%\Budgetier` |
| The program on macOS | `/Applications/Budgetier.app` |
| Your data on macOS | `~/Library/Application Support/Budgetier` |
| Your data on Linux | `~/.local/share/Budgetier` |

On Windows, Budgetier installs for the whole PC, which is why the installer asks for admin
rights. Each person's data stays in their own profile, on both systems. Updating or
uninstalling never touches it. To back up, copy the data folder. Budgetier also keeps the
previous version of `ledger.csv`, `imports.csv` and `accounts.json` beside each one, ending
in `.bak`, so if a file is ever damaged it tells you which one to put back. Inside the folder:

| File | What it is |
| --- | --- |
| `data/ledger.csv` | The permanent record of every transaction |
| `accounts.json` | Account names, types and entered balances |
| `rules.csv` | Your category rules |
| `imported/` | A copy of each imported file, needed to remove files safely |
| `splits.json` | Transactions you split into parts |
| `goals.json` | Your savings goals |
| `settings.json` | Your look, motion, the retirement estimate's numbers, where the window was left, what you'd seen last time, and whether you've seen the tour |
| `logs/app.log` | Details if something goes wrong |

## Bank sync

Instead of downloading files, you can update accounts through
[SimpleFIN](https://www.simplefin.org/), a paid service. Open the Accounts tab, choose
**Connect SimpleFIN**, and paste a setup token from your SimpleFIN account. Then match each
bank account to an account in Budgetier, or add it as a new one. Budgetier syncs only when
you press **Sync now**, and each sync brings in everything since the last one, however long
ago that was.

- **Privacy:** with sync on, SimpleFIN and the services behind it handle your transactions.
  Budgetier gets read-only access, sends SimpleFIN nothing but the request, and keeps the
  connection in Windows Credential Manager or the macOS Keychain, not the data folder.
- **History:** files stay the record for what they cover. A linked account only adds from
  its last imported day on. Near that day, or if you import a file later, the same amount
  within 3 days counts as the same transaction, because feeds word things differently.
- **Pending transactions** are skipped until they post.
- **Balances** come from the bank on every sync.
- **Rules** match the feed's descriptions too, and those can differ from your exports, so
  check Uncategorized after the first sync.
- **Disconnect** keeps your transactions. To cut off access completely, disable it on the
  SimpleFIN site as well.

Accounts that SimpleFIN can't reach can still be imported from files.

## Telling accounts apart

An account is a bank plus the last 4 digits of its number. Budgetier looks for
those in the file's columns, the lines above its header, then the filename.

Some exports contain no account number, including Fifth Third's. The review screen shows
what it found and asks for anything missing, so you never need to rename a file.

The first time an account appears, the review screen shows its guess at checking,
savings, credit card, loan, investing or retirement. If the file's amounts could be read either way, it also shows a
real row and asks whether that was money you spent. Your answers matter: a card that
reports purchases as positive would otherwise look like income.

## Balances

Many exports, especially cards, list transactions without a balance. Enter the current
balance from the bank's website when you import, or any time with **Edit** on the
Accounts tab. For a card, enter what you owe. Budgetier pins that figure to its date,
then adds new transactions on top and works backward for past months. The Accounts tab
and workbook mark these as calculated, and the Overview shows the total owed on cards.

Importing older history fills in past months without changing today's number. Enter
the posted balance, because pending charges aren't in it. If one was pending when you
entered the balance, the figure will end up off by that amount once it posts. A gap in
an account's history throws off every month before the gap. If a number drifts from
the bank's, enter it again. An export's own balance column always wins over an entered one.

## Investing and retirement accounts

Mark a brokerage account as **Investing**, and a 401(k), 403(b) or IRA as **Retirement**,
with **Edit** on the Accounts tab. Accounts linked through bank sync with names like these
are marked when you link them.

Markets change these balances without a transaction to show for it, so their past can't be
worked out from one balance. Instead each bank sync keeps that day's balance, as does each
one you enter, and the Investments tab shows growth from them: how much the balance rose
beyond what was paid in. Growth shows once there are two balances a while apart.

Inside these accounts nothing counts as income or spending. Money paid in or taken out is
`Contributions` or `Withdrawals`; dividends, trades and fees are `Investment Activity`,
which is part of growth. Banks word these rows many ways, so after you mark an account,
**Check what counts as paid in** lists its rows by name under each category. A change saves a
rule in the bank's wording, so new rows like it follow; wording too short to be safe changes
only those rows.

The retirement estimate grows today's retirement balance at the rate you choose, with the
same amount paid in each month, until the age you retire at. Rates are after inflation, so
amounts are in today's dollars. It's an estimate from the numbers you enter, not advice.
Its numbers are kept in `settings.json`.

## Loans and net worth

Mark a mortgage, car loan, student loan or line of credit as a **Loan**, and enter what you
owe on it, like a card. Accounts linked through bank sync with names like these are marked
when you link them, and a loan's balance always counts as owed, however the bank signs it.

A payment from checking that matches one into the loan, worded like a payment to a lender
or naming its bank, is a transfer: it pays the loan down rather than counting as spending,
and only the loan's interest counts, as `Interest`. Without the loan imported, a mortgage
payment is still Housing, as before.

The **Net worth** tab adds up everything you have, less everything you owe, at the end of
each month. An account counts from its first known balance, so one added partway through
shows as a step, and the change it reports is only how balances moved. Accounts without a
balance are left out, and it says which. It also shows what went to loans in the period:
how much was paid, how much of that was interest, and how much paid off the balance.

## PDFs

Synchrony Bank only exports PDFs. Choose the PDF in **Add files** and it's converted
automatically, or convert one by hand to look at the result:

```bash
.venv/Scripts/python -m budgetier.pdf2csv path/to/Synchrony.pdf
```

The account number comes from inside the PDF, so the filename doesn't matter. Its
columns don't line up on the page, so the converter reads word positions, then checks
every running balance against the row before it. If any row doesn't add up it stops
and writes nothing. Each new PDF should overlap the last one so the balances connect;
overlapping rows merge like any CSV. Only Synchrony's layout is supported, and scanned
PDFs with no text can't be read.

## Merging

Rows are compared by date, amount and description within an account, by count. If
a file shows a row three times and the ledger has it twice, one is added. So
overlapping exports don't double up, two identical coffees in one day both survive,
and importing the same file twice does nothing.

Pending rows are skipped when the file labels them. If a bank rewords a transaction
after it posts and you exported it before and after, it can appear twice; the
Transactions tab will show both.

## How money is counted

| Kind | Examples | Effect |
| --- | --- | --- |
| Expense | Purchases, bills | Counts as spending |
| Refund | Merchant refunds, insurance claims | Reduces spending |
| Estimated | A card payment with no imported purchases behind it | Counts as spending in its place |
| Income | Payroll, interest, unexplained deposits | Counts as income |
| Transfer | Card payments, moves between your accounts | Not counted, or purchases would count twice |
| Savings & Investing | Robinhood, online savings banks | A transfer, reported as saved |
| Contributions, Withdrawals | Paid into or taken out of an investing or retirement account | A transfer, reported as saved |
| Investment Activity | Dividends, trades and fees inside one | Not counted: it's part of growth |
| Loan payment | Paid into a loan | A transfer: it pays the loan down |
| Interest | What a loan charges | Counts as spending |

A card payment that matches a purchase history is a transfer, because the purchases
already count. If a card isn't imported, or its history doesn't reach back that far,
the payment counts as estimated spending, shown as `Card Payments (no detail)`. It's
the right size but the wrong detail: you can't see what was bought, and it lands in
the month you paid rather than the month you bought. Importing the card replaces it
automatically. The Accounts tab warns about these, about gaps in an account's history,
and about accounts that have fallen behind.

Averages skip months before your checking history starts, because those months have
no rent or income in them, and the month still in progress. The charts still show them.

## Categories

Add lines to `rules.csv` to override anything. Rules run first and apply to your
whole history on the next run. `match` is a case-insensitive regular expression
tested against the bank's description:

```text
match,category,merchant
CORNER BODEGA,Groceries,Corner Bodega
VENMO CASHOUT,Transfer,
```

A category of `Transfer` stops a row counting as spending or income. Any spending
category on an incoming payment makes it a refund against that category.

## Bank formats

Columns are found by name, so most banks work unmodified. Layouts for Chase, Capital
One, Discover, Citi, Bank of America, Apple Card, USAA, Ally, U.S. Bank, American
Express and Wells Fargo were written from memory of those formats, not real exports.
**Only Fifth Third has been tested against a real file**, so check the first import
from any other bank. If a file with a lone Amount column has its signs backwards,
remove the account on the Accounts tab and import it again, answering the "money you
spent" question the other way.

## Development

Budgetier runs on Windows, macOS and Linux and needs Python 3.12. Commands below use the
Windows path `.venv/Scripts/python`; elsewhere use `python3` to make the environment, then
`.venv/bin/python`.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
```

Run the desktop app. It uses your real data folder, so close any installed copy first:

```bash
.venv/Scripts/python run_app.py
```

| Path | What's there |
| --- | --- |
| `budgetier/` | The app: parsing, ledger, analysis and the workbook |
| `budgetier/views.py` | What each tab shows, worked out in cents, with no window |
| `budgetier/ui/` | The window, in Qt Widgets: one module per tab in `tabs/`, and the dialogs |
| `packaging/` | Installer, uninstaller and the scripts that build them |
| `tests/` | The test suite |
| `samples/` | A generator for fake bank exports |
| `VERSION` | The current version |

The look comes from `budgetier/ui/theme.py`: color tokens for each theme in light and dark,
sizes for type, spacing and corners, and the Qt style sheet made from them. To add a theme, add
its light and dark palettes there and to `PALETTES`. Dropdowns and menus are `ui/popup.py`, which
draws their panels, and motion is `ui/motion.py`, which every animation goes through so
**Reduce motion** can turn it all off. Anything that shows bank text goes through
`widgets.text()`, a table cell or a chart's note, which never read it as HTML.

Run the tests:

```bash
.venv/Scripts/python -m unittest discover -s tests -t .
.venv/Scripts/python -m ruff check .
```

The window's tests draw offscreen, so they need no screen, here or on CI. Open the app on fake
data, kept apart from your real data:

```bash
.venv/Scripts/python samples/make_samples.py
.venv/Scripts/python -m budgetier.ui --home samples/demo
```

The command-line version imports what's in a folder's `inbox/` and writes the workbook to
`output/budget.xlsx`. `--open` opens it:

```bash
.venv/Scripts/python -m budgetier --home samples/demo --open
```

Build the installer, one file that holds the whole app. A build only works for the system
it was made on. Windows makes `dist\Budgetier-Windows.exe` with `build.bat`:

```bash
build.bat
```

macOS makes a disk image in `dist` for that Mac's chip, and Linux makes
`dist/Budgetier-Linux.tar.gz`. On Ubuntu, `packaging/linux_deps.sh` installs what that needs:

```bash
sh build.sh
```

After a macOS or Linux build, this opens the app on fake data and checks every tab. On a Linux
machine with no screen, Qt draws offscreen:

```bash
.venv/bin/python packaging/self_check.py
```

Never commit real bank files. `.gitignore` blocks the usual ones, and test data must be
invented, including account numbers, names and addresses.

## Releasing

Work happens on `develop`, by pull request. CI runs the tests and builds the Linux app on
every pull request and on every push to `develop` and `main`, and opens the built app. Every
installer is made the same way, by `.github/workflows/build.yml`, which CI, Release, Mac builds
and Platform check each call. Linux is cheap and closest to a Mac, and Windows is tested by hand. To run a branch
on Windows or a Mac before a release, choose **Platform check** on the **Actions** tab, then
**Run workflow**.

To release, open the **Actions** tab, choose **Release**, then **Run workflow**, and pick
how to raise the version: `patch` for fixes, `minor` for features, `major` for big changes.
The workflow:

1. Merges `develop` into `main` and raises the number in `VERSION`, on a temporary
   `release/vX.Y.Z` branch.
2. Runs the tests and builds on Windows and Linux. If they fail, `main`
   and `develop` aren't touched.
3. Pushes `main` and a `vX.Y.Z` tag.
4. Publishes a GitHub release with those installers and their checksums.
5. Merges `main` back into `develop` and removes the temporary branch.
6. Unless you untick **Build for Mac**, runs **Mac builds**, which tests and builds on Apple
   Silicon and Intel macOS and adds both installers to the release. If that fails, the release
   still stands.

**Mac builds** can also be run by hand from the **Actions** tab, for a release that skipped
them or where they failed: give it the version, like `1.4.2`. Until a release has them, a Mac
isn't offered that update, and someone new has to take the Mac installer from an earlier release.

Add a `RELEASE_TOKEN` repository secret if `main` is protected, or if a release includes
changes to the workflow files: GitHub won't let the built-in token push those. The token
must be allowed to push to `main` and to change workflows.
