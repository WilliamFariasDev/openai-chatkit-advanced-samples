-- Migration: Fix constraints to allow simplified schema
-- Make old columns nullable so we can use only the 'item' column

-- Step 1: Make old columns nullable
ALTER TABLE public.messages
ALTER COLUMN role DROP NOT NULL;

ALTER TABLE public.messages
ALTER COLUMN content DROP NOT NULL;

-- Step 2: Verify the change
SELECT
    column_name,
    is_nullable,
    data_type
FROM information_schema.columns
WHERE table_name = 'messages'
AND table_schema = 'public'
ORDER BY ordinal_position;

-- You should see:
-- role: YES (nullable)
-- content: YES (nullable)
-- item: YES (nullable)

