
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
session.headers.update({"User-Agent": "RiftboundMetaBot/1.0"})


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
        encoding="utf-8",
    )


def fetch_decks():
    data = get_json(f"{BASE}/tournaments?per_page=30&page=1")

    if not data.get("success"):
        raise RuntimeError(f"RiftMana API error: {data}")

    results = data.get("data", {}).get("results", [])
    decks = []

    for item in results:
        deck_id = item.get("id")
        if not deck_id:
            continue

        deck_url = f"{BASE}/tournaments/{deck_id}/deck"

        try:
            detail = get_json(deck_url)
        except requests.RequestException as exc:
            print(f"Deck {deck_id} nicht abrufbar: {exc}")
            continue

        payload = detail.get("data", {})
        cards = payload.get("cards", [])

        if not cards:
            continue

        decks.append({
            "key": str(deck_id),
            "player": item.get("player_name") or "Unbekannt",
            "legend": item.get("legend_name") or "Unbekannt",
            "placement": item.get("placement", "?"),
            "event": item.get("event_name") or "Turnier",
            "date": item.get("date") or "",
            "players": item.get("players", "?"),
            "cards": cards,
            "url": deck_url,
        })

    return decks


def build_deck_embed(deck):
    embed = discord.Embed(
        title=f"RIFTBOUND-DECK | {deck['legend']}"[:256],
        description="Eine neue Deckliste wurde bei RiftMana gefunden.",
        url=deck["url"],
        color=discord.Color.from_rgb(88, 101, 242),
    )

    embed.add_field(
        name="Champion / Legend",
        value=str(deck["legend"])[:1024],
        inline=True,
    )
    embed.add_field(
        name="Platzierung",
        value=str(deck["placement"])[:1024],
        inline=True,
    )
    embed.add_field(
        name="Spieler",
        value=str(deck["player"])[:1024],
        inline=True,
    )
    embed.add_field(
        name="Turnier",
        value=str(deck["event"])[:1024],
        inline=False,
    )

    if deck["date"]:
        embed.add_field(
            name="Datum",
            value=str(deck["date"])[:100],
            inline=True,
        )

    if deck["players"] not in (None, "", "?"):
        embed.add_field(
            name="Teilnehmer",
            value=str(deck["players"])[:100],
            inline=True,
        )

    embed.set_footer(text="Riftbound Meta Bot • Daten von RiftMana")
    return embed


def build_card_embeds(deck):
    # Separate Embeds für die Karten, damit sie garantiert mitgesendet werden.
    card_lines = []

    for card in deck["cards"]:
        name = str(card.get("name") or "Unbekannte Karte")
        quantity = card.get("quantity", 1)
        code = str(card.get("code") or "")

        line = f"**{quantity}×** {name}"
        if code:
            line += f" (`{code}`)"
        card_lines.append(line)

    # Teile die Kartenliste in Abschnitte auf, die Discord akzeptiert.
    chunks = []
    current = []
    current_length = 0

    for line in card_lines:
        if current and current_length + len(line) + 1 > 3500:
            chunks.append(current)
            current = []
            current_length = 0

        current.append(line)
        current_length += len(line) + 1

    if current:
        chunks.append(current)

    embeds = []

    for index, chunk in enumerate(chunks):
        title = "KARTENLISTE"
        if len(chunks) > 1:
            title += f" • TEIL {index + 1}/{len(chunks)}"

        embed = discord.Embed(
            title=title,
            description="\n".join(chunk),
            url=deck["url"],
            color=discord.Color.from_rgb(46, 204, 113),
        )
        embed.set_footer(
            text=f"{len(card_lines)} Karteneinträge • Deckdaten bei RiftMana"
        )
        embeds.append(embed)

    return embeds


async def main():
    state = load_state()
    seen = set(state.get("seen", []))

    decks = await asyncio.to_thread(fetch_decks)

    if not state.get("initialized", False):
        state["seen"] = sorted(seen | {deck["key"] for deck in decks})
        state["initialized"] = True
        save_state(state)
        print(f"Erster Scan: {len(decks)} Decks registriert.")
        return

    new_decks = [deck for deck in decks if deck["key"] not in seen]

    if not new_decks:
        print("Keine neuen Decks gefunden.")
        return

    client = discord.Client(intents=discord.Intents.none())

    try:
        await client.login(TOKEN)
        channel = await client.fetch_channel(CHANNEL_ID)

        for deck in reversed(new_decks):
            # 1. Nachricht: übersichtliche Turnierdaten
            await channel.send(
                embed=build_deck_embed(deck),
                allowed_mentions=discord.AllowedMentions.none(),
            )

            # 2. und weitere Nachrichten: vollständige Kartenliste
            for card_embed in build_card_embeds(deck):
                await channel.send(
                    embed=card_embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )

            seen.add(deck["key"])
            print(f"Deck gepostet: {deck['legend']} – {deck['player']}")

        state["seen"] = sorted(seen)
        state["initialized"] = True
        save_state(state)

        print(f"{len(new_decks)} neue Decks gepostet.")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
