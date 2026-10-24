
import asyncio
import json
import os
from pathlib import Path

import discord
import requests

BASE = "https://riftmana.com/wp-json/riftmana/v2"
TOKEN = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
STATE_FILE = Path("seen_decks.json")

session = requests.Session()
session.headers.update({
    "User-Agent": "RiftboundMetaBot/1.0"
})


def get_json(url):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"initialized": False, "seen": []}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def fetch_decks():
    data = get_json(
        f"{BASE}/tournaments?per_page=30&page=1"
    )

    if not data.get("success"):
        raise RuntimeError(f"RiftMana API error: {data}")

    results = data.get("data", {}).get("results", [])
    decks = []

    for item in results:
        tournament_id = item.get("id")
        if not tournament_id:
            continue

        deck_url = f"{BASE}/tournaments/{tournament_id}/deck"

        try:
            detail = get_json(deck_url)
        except requests.RequestException as exc:
            print(f"Deck {tournament_id} nicht abrufbar: {exc}")
            continue

        payload = detail.get("data", {})
        cards = payload.get("cards", [])

        if not cards:
            continue

        key = str(tournament_id)
        decks.append({
            "key": key,
            "player": item.get("player_name", "Unbekannt"),
            "legend": item.get("legend_name", "Unbekannt"),
            "placement": item.get("placement", "?"),
            "event": item.get("event_name", "Turnier"),
            "date": item.get("date", ""),
            "players": item.get("players", "?"),
            "cards": cards,
            "url": deck_url,
        })

    return decks


def format_deck(deck):
    lines = [
        "**Neue Riftbound-Deckliste**",
        f"**Legend:** {deck['legend']}",
        f"**Spieler:** {deck['player']}",
        f"**Platzierung:** {deck['placement']}",
        f"**Turnier:** {deck['event']}",
        f"**Datum:** {deck['date']}",
        f"**Teilnehmer:** {deck['players']}",
        "",
        "**Karten:**",
    ]

    for card in deck["cards"][:50]:
        name = card.get("name", "Unbekannte Karte")
        quantity = card.get("quantity", 1)
        code = card.get("code", "")
        suffix = f" ({code})" if code else ""
        lines.append(f"• {quantity}x {name}{suffix}")

    lines.extend([
        "",
        f"[Deckdaten öffnen]({deck['url']})"
    ])

    return "\n".join(lines)


async def main():
    state = load_state()
    seen = set(state.get("seen", []))

    decks = await asyncio.to_thread(fetch_decks)

    if not state.get("initialized", False):
        state["seen"] = sorted(seen | {
            deck["key"] for deck in decks
        })
        state["initialized"] = True
        save_state(state)
        print(f"Erster Scan: {len(decks)} Decks registriert.")
        return

    new_decks = [
        deck for deck in decks
        if deck["key"] not in seen
    ]

    client = discord.Client(
        intents=discord.Intents.none()
    )

    try:
        await client.login(TOKEN)
        channel = await client.fetch_channel(CHANNEL_ID)

        for deck in reversed(new_decks):
            message = format_deck(deck)

            # Discord erlaubt maximal 2000 Zeichen pro Nachricht.
            if len(message) > 1900:
                message = message[:1850] + "\n\n[Liste gekürzt]"

            await channel.send(
                message,
                allowed_mentions=discord.AllowedMentions.none()
            )
            seen.add(deck["key"])

        state["seen"] = sorted(seen)
        state["initialized"] = True
        save_state(state)

        print(f"{len(new_decks)} neue Decks gepostet.")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
