# Telegram City Guide Bot — Batumi & Kobuleti (Georgia) — PRO

✅ Favorites • ✅ Inline mode • ✅ Filters (kids/dog/price) • ✅ CSV Import (from Google Sheets export) • ✅ RU/EN

## Run on Replit (browser-only)
1) Replit → Create Repl → Import from ZIP → upload this archive.
2) Secrets (lock icon): add `BOT_TOKEN` from @BotFather.
3) Click **Run**. It will: install deps → seed DB → start bot.
4) In Telegram: `/start`

## Commands
- `/city` — choose city (inline buttons)
- `/nearby` — nearby places (no external APIs)
- `/search <query>` — search by name/description
- `/random` — random place
- `/fav` — show your favorites
- `/lang` — choose RU/EN
- `/filters` — toggle kids-/dog-friendly, set price 1–4
- Admin-ish:
  - `/import_csv` — instructions how to import CSV
  - Upload a CSV file to the bot (as a document) to import places

## Favorites
Each place card has a **❤️ Add/Remove Favorite** button. Also via `/fav` list.

## Inline Mode
In any chat: type `@YourBotName batumi pizza` → pick a place to send as a card.

## Filters
- Kids-friendly (👶) toggle
- Dog-friendly (🐶) toggle
- Price level: 1–4 (₁₋₄)
Filters apply to `/search`, category lists, and `/nearby`.

## CSV Import (Google Sheets)
1) Keep columns: `city,name,category,lat,lon,description,address,hours,rating,url,kids_friendly,dog_friendly,price_level`
2) In Google Sheets → File → Download → **CSV**
3) Send the CSV to the bot as a **document** (the bot will parse & import).

## i18n
- `/lang` to switch.
- Default RU. Bot stores per-user language.

Enjoy!
