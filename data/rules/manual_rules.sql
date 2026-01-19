-- Manual high-priority rules
-- These override learned rules for specific cases

INSERT INTO merchant_rules (rule_pack, priority, match_type, match_value, match_detail, category, subcategory, is_active, created_by, notes)
VALUES
  ('manual', 10, 'exact', 'ZELLE TO', 'DEVI DAYCARE', 'Baby', 'Daycare', TRUE, 'manual', 'Daycare payments via Zelle'),
  ('manual', 10, 'exact', 'ZELLE FROM', 'ROBERT DIENSTAG', 'Income', 'Family Support', TRUE, 'manual', 'Weekly support from father'),
  ('manual', 10, 'exact', 'EAST PARK BEVERAGE', NULL, 'Food & Drink', 'Alcohol', TRUE, 'manual', 'Alcohol purchases (no longer buying vape products)');
