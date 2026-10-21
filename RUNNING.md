# Running Spendwise

This guide takes you from a fresh copy of the project to a running app and a passing test
suite. Commands are given for **Linux/macOS** (bash or zsh) and **Windows PowerShell**.

> The Linux commands in this guide were run exactly as written on Linux with Python 3.11,
> 3.12 and 3.13. **The Windows PowerShell commands have not been run on a Windows computer.**
> They use standard Windows Python behaviour, but if one fails, see
> [Troubleshooting](#troubleshooting).

## 1. Requirements

- **Python 3.11 or newer** (tested with 3.11, 3.12 and 3.13). Check with
  `python3 --version` (Linux/macOS) or `py --version` (Windows).
- No other software. SQLite is built into Python.

All commands below are run from the project's top folder, the one that contains
`requirements.txt` and the `app` folder.

## 2. What a virtual environment is

A virtual environment (a "venv") is a private folder of Python packages for one project. It
keeps Spendwise's dependencies (Flask and friends) separate from everything else on your
computer, so projects cannot break each other. The folder is called `.venv`; it is
disposable, is not committed to Git, and can be deleted and recreated at any time.

## 3. Create the virtual environment and install dependencies

**Linux/macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

When the environment is active, your prompt starts with `(.venv)`. You must activate it
again in every new terminal window. To leave it, run `deactivate`.

`requirements.txt` lists two packages: **Flask** (needed to run the app) and **pytest**
(needed only to run the tests). Their own dependencies are installed automatically.

Optional check that nothing is broken: `pip check` should print
`No broken requirements found.`

## 4. Environment variables

Spendwise reads two environment variables. It does **not** read a `.env` file, so there is
no `.env` file to create.

| Variable | Meaning |
| --- | --- |
| `SPENDWISE_ENV` | `development` or `production`. **If unset, it means `production`.** Any other value stops the app with an error. |
| `SPENDWISE_SECRET_KEY` | A long random string used to sign the session cookie and CSRF tokens. **Required in production**, at least 32 characters, and it must not be the built-in development key. Optional in development. |

### Option A: local development (easiest)

Set `SPENDWISE_ENV` to `development`. Without a key, the app uses a fixed, insecure,
development-only key. That is fine on your own computer and not acceptable anywhere else.

**Linux/macOS**

```bash
export SPENDWISE_ENV=development
```

**Windows PowerShell**

```powershell
$env:SPENDWISE_ENV = "development"
```

### Option B: production mode with your own secret key

Generate a key (it prints 64 random hexadecimal characters):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the printed value and set it. **Never commit the key to Git, put it in a screenshot, or
share it.** Generate a different key for each installation.

**Linux/macOS**

```bash
export SPENDWISE_SECRET_KEY="paste-the-generated-value-here"
unset SPENDWISE_ENV            # unset means production
```

**Windows PowerShell**

```powershell
$env:SPENDWISE_SECRET_KEY = "paste-the-generated-value-here"
Remove-Item Env:SPENDWISE_ENV -ErrorAction SilentlyContinue
```

These variables last only for the current terminal window. If you change the secret key
later, anyone with an open page will simply need to reload it before submitting a form.

> There is deliberately no `.env.example` file: the app does not load `.env` files, so such a
> file would suggest a feature that does not exist.

## 5. Start the application

With the virtual environment active and the environment variables set:

```bash
flask --app app run
```

(The same command works in PowerShell.) Flask prints a line like
`Running on http://127.0.0.1:5000`. Open <http://127.0.0.1:5000> in your browser. Stop the
server with `Ctrl+C`.

To use a different port: `flask --app app run --port 8000`.

This uses Flask's built-in development server, which is meant for your own computer only. It
is the only way of running the app that this project documents or tests. Do not expose it to
the internet.

### How the database is created

You do not create the database yourself. When the app starts, it creates the folder
`instance/` in the project folder and a SQLite file `instance/spendwise.sqlite` with the
`transactions` table (from `app/schema.sql`). Starting again later reuses the file and keeps
your data; the creation step is safe to repeat.

- Your data is in that one file. To back it up, stop the app and copy the file.
- To start from an empty database, stop the app and delete `instance/spendwise.sqlite`.
- The `instance/` folder is excluded from Git because it holds your personal financial data.

## 6. Run the tests

With the virtual environment active:

```bash
python -m pytest
```

Expected result: `369 passed`. The tests use temporary databases and do not need any
environment variables or a running server, and they never touch `instance/spendwise.sqlite`.

## 7. Troubleshooting

**`RuntimeError: SPENDWISE_SECRET_KEY is not set`**
You started the app in production mode (the default when `SPENDWISE_ENV` is unset) without a
key. For local use, set `SPENDWISE_ENV=development` (section 4, option A). Otherwise generate
and set a key (option B).

**`SPENDWISE_SECRET_KEY is too short`**
The key must be at least 32 characters. Use the generator command in option B.

**`SPENDWISE_SECRET_KEY must not be the development fallback key`**
Do not copy the development key into production. Generate a fresh one.

**`SPENDWISE_ENV must be one of production, development`**
The value is misspelled (for example `dev` or `prod`). Use exactly `development` or `production`.

**`flask: command not found` / `'flask' is not recognized`**
The virtual environment is not active, or dependencies are not installed. Activate it
(section 3) and run `pip install -r requirements.txt`. You can also run Flask without
activating, by naming the environment's Python directly:
`.venv/bin/python -m flask --app app run` (Linux/macOS) or
`.\.venv\Scripts\python.exe -m flask --app app run` (Windows).

**PowerShell says "running scripts is disabled on this system"** when activating
Allow locally created scripts for your user account, then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

If you prefer not to change that setting, skip activation and use the
`.\.venv\Scripts\python.exe -m ...` form shown above.

**`py` is not recognized on Windows**
Install Python from python.org and tick "Add python.exe to PATH" (or keep the "py launcher"
option ticked), then open a new PowerShell window. You can use `python` in place of `py`.

**`Address already in use` / port 5000 is busy**
Another program (on macOS, often AirPlay Receiver) is using the port. Start on another one:
`flask --app app run --port 8000`.

**"That form could not be verified" (a 403 page)**
The page's security token no longer matches your session, for example because the server
restarted with a different secret key or your browser blocks cookies. Go back, reload the
page and submit again.

**I want a clean slate**
Stop the app, delete `instance/spendwise.sqlite` (your data) and, if you like, delete `.venv`
and repeat from section 3.
