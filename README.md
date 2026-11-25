# Loan approval workflow

A lightweight FastAPI application for anonymous loan applications and a staff approval queue.

## Roles and workflow

- **Customer:** submits an application without an account and uses a private tracking code to check its status.
- **Loan Coordinator:** reviews new applications and forwards them to Level 1 or rejects them with a reason.
- **Loan Approval Level 1:** approves applications for Level 2 review or rejects them with a reason.
- **Loan Approval Level 2:** approves applications for finance or rejects them with a reason.
- **Finance - Fund Disbursement:** marks approved applications as funded after disbursement.
- **Admin:** views the queue and creates staff accounts. Admins do not approve or disburse loans.

Each staff action is recorded in the application's activity history. Customers do not need to sign in; staff accounts are protected by password login.

## Run locally

Set the first admin's credentials before starting the app:

```bash
export LOAN_ADMIN_USERNAME=admin
export LOAN_ADMIN_PASSWORD='choose-a-long-unique-password'
export SESSION_SECRET='choose-a-long-random-secret'
python -m pip install -e '.[dev]'
myapp
```

Open <http://localhost:8000>. The first admin account is created on the first API request. Use the staff sign-in form to create coordinator, approval, finance, and additional admin accounts. Passwords must be at least 12 characters.

The SQLite database defaults to `loan_workflow.sqlite3` in the current directory. Set `LOAN_DB_PATH` to choose another location. In production, set a persistent `SESSION_SECRET`, serve over HTTPS, and set `COOKIE_SECURE=1`.

## API overview

- `POST /api/applications` — anonymous application submission
- `GET /api/track/{tracking_code}` — anonymous status lookup
- `POST /api/login`, `POST /api/logout`, `GET /api/me` — staff session
- `GET /api/applications` — authenticated staff queue
- `POST /api/applications/{id}/actions` — role- and stage-checked workflow action
- `POST /api/staff` — admin-only staff account creation

Run tests with `pytest`.
