-- migrate:up

-- Phone numbers in European national formats (docs/build-spec.md §9.10):
-- German mobiles have 11 or 12 digits, more than CHAR(10) holds. VARCHAR(15)
-- fits any number, since international numbers have at most 15 digits.
ALTER TABLE CUSTOMER ALTER COLUMN PHONE TYPE VARCHAR(15);
ALTER TABLE SHIPPING_DETAILS ALTER COLUMN PHONE TYPE VARCHAR(15);

-- migrate:down

-- Fails while any phone is longer than 10 characters.
ALTER TABLE CUSTOMER ALTER COLUMN PHONE TYPE CHAR(10);
ALTER TABLE SHIPPING_DETAILS ALTER COLUMN PHONE TYPE CHAR(10);
