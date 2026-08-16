-- Add the two lightly-used personal Chase credit cards (each paid via autopay
-- from the joint checking account already in the DB).
--
-- There is no accounts CRUD UI/API, so new accounts are added directly. Run
-- this against the target DB (prod is applied separately from code deploys —
-- see MAINTENANCE.md). Rename the account_name values below to whatever you
-- want shown in the app before running; you can also UPDATE them later.
--
-- Idempotent: re-running won't create duplicates (guarded on account_name).

INSERT INTO accounts (account_name, account_type, institution, is_active)
SELECT v.account_name, v.account_type, v.institution, TRUE
FROM (VALUES
    ('Chase Freedom Credit - Andrew', 'credit', 'Chase'),
    ('Chase Freedom Credit - Amanda', 'credit', 'Chase')
) AS v(account_name, account_type, institution)
WHERE NOT EXISTS (
    SELECT 1 FROM accounts a WHERE a.account_name = v.account_name
);

-- Note on double-counting: each card's monthly autopay already appears as an
-- outflow in Chase Checking. Once you import a card's line-item charges, treat
-- that checking-side "CHASE CREDIT CARD PAYMENT" as a transfer / exclude it
-- from budget so the same money isn't counted twice (same handling the Sapphire
-- card already gets).
