
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlencode

import discord
import requests

API = "https://www.riftools.app/api"
STATE_FILE = Path("seen_decks.json")
MAX_TOURNAMENTS = 10

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])

HEADERS = {
    "User-Agent": "RiftboundMetaBot/1.0 (personal Discord bot)"
}


def get_json(url):
    response = requests.get(
        url, headers=HEADERS, timeout=30
    )
    response.raise_for_status()
    return response.json()


def load_state():
    if not STATE_FILE.exists():
        return {"initialized": False, "seen": []}

    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_tournaments():
    data = get_json(f"{API}/tournaments")
    items = data.get("items", [])

    # Sort newest first when dates are available.
    return sorted(
        items,
        key=lambda item: str(item.get("event_date", "")),
        reverse=True
    )[:MAX_TOURNAMENTS]


def collect_decks():
    found = []

    for event in get_tournaments():
        event_url = event.get("tournament_url")
        if not event_url:
            continue

        query = urlencode({"url": event_url})
        detail = get_json(f"{API}/tournament?{query}")

        tournament = detail.get("tournament", {})
        tournament_name = (
            tournament.get("name")
            or event.get("name")
            or "Riftbound tournament"
        )

        for row in detail.get("rows", []):
            deck_url = row.get("deck_url")
            if not deck_url:
                continue

            player = row.get("player_name") or "Unknown player"
            legend = row.get("legend_name") or "Unknown legend"
            rank = row.get("rank") or row.get("placement") or "?"
            placement = row.get("placement") or rank

            # Stable identifier for each published deck entry.
            key = str(deck_url).strip()
            if not key:
                continue

            # Only publish normal web links.
            link = (
                deck_url if deck_url.startswith(("https://", "http://"))
                else event_url
            )

            found.append({
                "key": key,
                "player": player,
                "legend": legend,
                "rank": rank,
                "placement": placement,
                "event": tournament_name,
                "event_url": event_url,
                "deck_url": link,
                "date": event.get("event_date", "")
            })

    # Remove duplicates in the current scan.
    unique = {}
    for deck in found:
        unique[deck["key"]] = deck

    return list(unique.values())


def format_message(deck):
    return (
        f"**Neue Riftbound-Deckliste**\n"
        f"**Legend:** {deck['legend']}\n"
        f"**Spieler:** {deck['player']}\n"
        f"**Platzierung:** {deck['placement']}\n"
        f"**Turnier:** {deck['event']}\n"
        f"**Datum:** {deck['date'] or 'Nicht angegeben'}\n"
        f"[Deckliste / Turnier öffnen]({deck['deck_url']})"
    )


async def main():
    state = load_state()
    seen = set(state.get("seen", []))

    # First run: register existing decks without flooding Discord.
    decks = await asyncio.to_thread(collect_decks)

    if not state.get("initialized", False):
        state["seen"] = sorted(
            seen | {deck["key"] for deck in decks}
        )
        state["initialized"] = True
        save_state(state)
        print(f"Initial scan complete: {len(decks)} decks registered.")
        return

    new_decks = [
        deck for deck in decks if deck["key"] not in seen
    ]

    intents = discord.Intents.none()
    client = discord.Client(intents=intents)

    try:
        await client.login(TOKEN)
        channel = await client.fetch_channel(CHANNEL_ID)

        # Older discoveries first.
        for deck in reversed(new_decks):
            await channel.send(
                format_message(deck),
                allowed_mentions=discord.AllowedMentions.none()
            )
            seen.add(deck["key"])

        state["seen"] = sorted(seen)
        state["initialized"] = True
        save_state(state)

        print(f"Posted {len(new_decks)} new deck lists.")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
