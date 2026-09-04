-- Store the last 4 digits of each account/card number so the import UI can
-- auto-select the right account from a Chase CSV filename (Chase####_Activity...).
--
-- The column is nullable: accounts without a last4 simply don't auto-match and
-- fall back to manual selection.

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last4 VARCHAR(4);

COMMENT ON COLUMN accounts.last4 IS
    'Last 4 digits of the account/card number. Used to auto-match an uploaded '
    'Chase CSV filename (Chase####_Activity...) to this account in the import UI.';

-- Fill in the real last-4 for each account, then re-run these. Chase names its
-- export files Chase<last4>_Activity_YYYYMMDD.CSV, so the digits here must match
-- the digits in the filename. Left as placeholders on purpose — edit before running.
--
-- UPDATE accounts SET last4 = '0000' WHERE account_name = 'Chase Checking';
-- UPDATE accounts SET last4 = '0000' WHERE account_name = 'Chase Sapphire Credit';
-- UPDATE accounts SET last4 = '0000' WHERE account_name = 'Chase Freedom Credit - Andrew';
-- UPDATE accounts SET last4 = '0000' WHERE account_name = 'Chase Freedom Credit - Amanda';
