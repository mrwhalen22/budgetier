# Budgetier

Merges CSV exports from your banks and cards into one continuous history per
account, then shows your monthly spending, recurring payments, largest expenses
and savings. Everything runs on this machine, and your data stays here unless you turn on
[bank sync](#bank-sync). The dashboard is a single offline file that makes no network requests.
The app itself asks GitHub for the latest version when it opens; see [Updates](#updates).

## Use it

Download the installer for your system from the [latest release](../../releases/latest).

**Windows:** run `Budgetier-Windows.exe` and approve the admin prompt. It installs for everyone
on the PC, with your choice of location and shortcuts, and appears in Windows' Installed
Apps, where you can uninstall it. It needs Microsoft's WebView2 runtime, which comes with
Windows 11. The installer isn't code signed, so Windows may warn you the first time; choose
**More info**, then **Run anyway**. Then open **Budgetier** from the Start menu or desktop.

**macOS:** choose `Budgetier-macOS-Apple-Silicon.dmg` for an M-series Mac, or `Budgetier-macOS-Intel.dmg`
for an Intel one. Apple menu > **About This Mac** shows which you have. Open the file and
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
- **Budgets** sets a monthly target for a category, as a dollar amount or a percent of
  income, and shows what's left. A percent target follows each month's income. While a
  month is still in progress it uses the average of the last 3 complete months instead,
  because your pay may not have landed yet.
- **Accounts** is where you edit an account, set a balance, remove one imported file or
  a whole account, export the Excel workbook, and open the data folder.
- **Help** shows which banks work, tips for accurate numbers, and a short tour.

Removing a file rebuilds that account from its other files, so transactions another
file also covers stay.

## Updates

When the installed app opens, it asks GitHub for the latest release. No financial data goes
with that request, and being offline is fine. If there's a newer version, **Update to x.y.z**
appears in the sidebar. Nothing downloads until you choose it, and the download must match the
release's `SHA256SUMS.txt`.

- **Windows:** Budgetier closes, Windows asks for permission, and it opens again when it's done.
- **macOS:** the download opens, and you drag Budgetier to Applications to replace the old copy.

Your data is kept apart from the program, so updating doesn't touch it. To stop the automatic
check, or to check by hand, use the buttons at the bottom of the Help tab.

## Appearance

Choose **Appearance** at the bottom of the sidebar to pick a theme (Pine, Ocean or Plum) and
light, dark or matching your system. The choice is remembered on this computer.

## Where things live

| What | Where |
| --- | --- |
| The program on Windows | `C:\Program Files\Budgetier` |
| Your data on Windows | `%LOCALAPPDATA%\Budgetier` |
| The program on macOS | `/Applications/Budgetier.app` |
| Your data on macOS | `~/Library/Application Support/Budgetier` |

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
| `logs/app.log` | Details if something goes wrong |

## Bank sync

Instead of downloading files, you can update accounts through
[SimpleFIN](https://www.simplefin.org/), a paid service. Open the Accounts tab, choose
**Connect SimpleFIN**, and paste a setup token from your SimpleFIN account. Then match each
bank account to an account in Budgetier, or add it as a new one. Budgetier syncs when it
opens, at most every 6 hours, and whenever you press **Sync now**.

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
savings or credit card. If the file's amounts could be read either way, it also shows a
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

Budgetier runs on Windows and macOS and needs Python 3.12. Commands below use the Windows
path `.venv/Scripts/python`; on macOS use `python3` to make the environment, then
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
| `budgetier/` | The app: parsing, ledger, analysis, reports, dashboard page and desktop window |
| `packaging/` | Installer, uninstaller and the scripts that build them |
| `tests/` | The test suite |
| `samples/` | A generator for fake bank exports |
| `VERSION` | The current version |

The look comes from the design system at the top of `budgetier/dashboard.html`: tokens for
color, type, spacing and corners, then one button, field, card, panel, banner and table. To add
a theme, add its light and dark palettes there and to `PALETTES`. `tests/test_design.py` fails
on hard-coded colors or sizes, inline looks, and any theme with unreadable contrast.

Run the tests:

```bash
.venv/Scripts/python -m unittest discover -s tests -t .
.venv/Scripts/python -m ruff check .
```

Try the command-line version on fake data, kept apart from your real data:

```bash
.venv/Scripts/python samples/make_samples.py
.venv/Scripts/python -m budgetier --home samples/demo --open
```

Build the installer, one file that holds the whole app. A build only works for the system
it was made on. Windows makes `dist\Budgetier-Windows.exe` with `build.bat`:

```bash
build.bat
```

macOS makes a disk image in `dist` for that Mac's chip:

```bash
sh build.sh
```

After a macOS build, this opens the app on fake data and checks every tab:

```bash
.venv/bin/python packaging/self_check.py
```

Never commit real bank files. `.gitignore` blocks the usual ones, and test data must be
invented, including account numbers, names and addresses.

## Releasing

Work happens on `develop`, by pull request. CI runs the tests and builds the installers on
Windows on every pull request and on every push to `develop` and `main`, and opens the built
app. Mac runners cost far more, so **Mac CI** only runs on a pull request that changes something
that can behave differently on a Mac, such as `budgetier/app.py` or `packaging/`. To run it on
anything else, choose **Mac CI** on the **Actions** tab, then **Run workflow** and the branch.

To release, open the **Actions** tab, choose **Release**, then **Run workflow**, and pick
how to raise the version: `patch` for fixes, `minor` for features, `major` for big changes.
The workflow:

1. Merges `develop` into `main` and raises the number in `VERSION`, on a temporary
   `release/vX.Y.Z` branch.
2. Runs the tests and builds on Windows. If they fail, `main`
   and `develop` aren't touched.
3. Pushes `main` and a `vX.Y.Z` tag.
4. Publishes a GitHub release with the Windows installer and its checksum.
5. Merges `main` back into `develop` and removes the temporary branch.
6. Unless you untick **Build for Mac**, runs **Mac builds**, which tests and builds on Apple
   Silicon and Intel macOS and adds both installers to the release. If that fails, the Windows
   release still stands.

**Mac builds** can also be run by hand from the **Actions** tab, for a release that skipped
them or where they failed: give it the version, like `1.4.2`. Until a release has them, a Mac
isn't offered that update, and someone new has to take the Mac installer from an earlier release.

Add a `RELEASE_TOKEN` repository secret if `main` is protected, or if a release includes
changes to the workflow files: GitHub won't let the built-in token push those. The token
must be allowed to push to `main` and to change workflows.
