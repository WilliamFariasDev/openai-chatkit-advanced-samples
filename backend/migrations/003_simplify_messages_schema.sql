-- Migration: Simplify messages table to store ThreadItem directly
-- This eliminates the need for role/content columns which don't apply to all item types

-- Step 1: Add new item column
ALTER TABLE public.messages
ADD COLUMN item JSONB;

-- Step 2: Migrate existing data (copy raw to item)
UPDATE public.messages
SET item = raw
WHERE raw IS NOT NULL;

-- Step 3: Make item NOT NULL (after data migration)
ALTER TABLE public.messages
ALTER COLUMN item SET NOT NULL;

-- Step 4: Drop old columns (optional - can keep for backward compatibility)
-- Uncomment these if you want to fully migrate:
ALTER TABLE public.messages DROP COLUMN role;
ALTER TABLE public.messages DROP COLUMN content;
ALTER TABLE public.messages DROP COLUMN raw;

-- Step 5: Add index on item for JSON queries if needed
CREATE INDEX idx_messages_item_type ON public.messages((item->>'type'));

-- Verify migration
SELECT
    COUNT(*) as total_messages,
    COUNT(item) as messages_with_item,
    COUNT(raw) as messages_with_raw
FROM public.messages;

COMMENT ON COLUMN public.messages.item IS 'Complete ThreadItem object stored as JSONB. Contains all fields including type, role (if applicable), content, etc.';

