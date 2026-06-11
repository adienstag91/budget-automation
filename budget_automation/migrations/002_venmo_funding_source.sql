-- Capture the Venmo "Funding Source" and "Destination" columns so enrichment can
-- tell balance-affecting payments (received to / spent from the Venmo balance)
-- from bank/card-funded ones (which bypass the balance and already appear on the
-- bank statement). This is what makes cashout reconciliation deterministic.

ALTER TABLE venmo_transactions_raw
    ADD COLUMN IF NOT EXISTS funding_source VARCHAR(200),
    ADD COLUMN IF NOT EXISTS destination VARCHAR(200);

COMMENT ON COLUMN venmo_transactions_raw.funding_source IS
    'Venmo "Funding Source" column. "Venmo balance" => spent from balance (not on bank statement); a bank/card => bank-funded (already on bank statement).';
COMMENT ON COLUMN venmo_transactions_raw.destination IS
    'Venmo "Destination" column. "Venmo balance" => received into balance; a bank => cashout/instant-deposit.';
