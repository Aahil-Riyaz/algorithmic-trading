"""Official Discord bot for the prospective paper ledger. No personal tokens or account trading."""
import asyncio
from datetime import datetime, timezone
import json
import logging
import os

import discord
from discord import app_commands
from discord.ext import tasks

from aahil_wave import ACTIVE, connect, price, render, scoreboard, states
from wave_paper_service import catch_up


def sync_feed():
    db=connect()
    try:
        catch_up(db)
    finally:
        db.close()


def board_text(store):
    s=scoreboard(store)
    def pct(v):
        return "n/a" if v is None else f"{v:.1%}"
    ci=s["signal_day_bootstrap_95"]
    interval=f"{ci[0]:+.2f} to {ci[1]:+.2f}R" if ci else "insufficient closed days"
    mean=s["net_r_per_closed"]
    expectation="n/a" if mean is None else f"{mean:+.3f}R"
    counts=", ".join(f"{k} {v}" for k,v in s["statuses"].items()) or "none"
    return (f"Aahil Wave • prospective paper\n{s['signals']} logged, {s['skipped']} skipped, {s['closed']} closed\n"
            f"Fill rate {pct(s['fill_rate'])} • invalidation {pct(s['invalidation_rate'])}\n"
            f"Net after fees/slippage/funding {s['net_r']:+.2f}R • mean/close {expectation}\n"
            f"Mean R/close 95% interval {interval}\n{counts}")


class WaveClient(discord.Client):
    def __init__(self, channel_id):
        super().__init__(intents=discord.Intents.none(),allowed_mentions=discord.AllowedMentions.none())
        self.channel_id=channel_id
        self.tree=app_commands.CommandTree(self)
        self.store=connect()
        self.store.execute("CREATE TABLE IF NOT EXISTS boards(channel INTEGER PRIMARY KEY, message INTEGER, text TEXT)")

    async def setup_hook(self):
        await self.tree.sync()
        self.publish.start()

    @tasks.loop(seconds=30)
    async def publish(self):
        try:
            await asyncio.to_thread(sync_feed)
            channel = self.get_channel(self.channel_id) or await self.fetch_channel(self.channel_id)
            events = self.store.execute("""SELECT e.* FROM events e LEFT JOIN delivery d USING(seq)
                WHERE d.seq IS NULL AND e.kind NOT IN ('account','bar','skip') ORDER BY e.seq LIMIT 50""").fetchall()
            for event in events:
                body = render(event)
                # Avoid presenting an old queued setup as a new executable entry after a disconnect.
                if event["kind"]=="signal" and datetime.now(timezone.utc).timestamp()-event["ts"]>=60:
                    self.store.execute("INSERT OR IGNORE INTO delivery VALUES(?,?)",(event["seq"],"missed_freshness_window"))
                    continue
                msg = await channel.send(body,nonce=event["seq"])
                self.store.execute("INSERT OR IGNORE INTO delivery VALUES(?,?)",(event["seq"],str(msg.id)))
            text=board_text(self.store)
            board=self.store.execute("SELECT * FROM boards WHERE channel=?",(self.channel_id,)).fetchone()
            if board is None or board["text"]!=text:
                if board is not None:
                    try:
                        msg=await channel.get_partial_message(board["message"]).edit(content=text)
                    except discord.NotFound:
                        msg=await channel.send(text)
                else:
                    msg=await channel.send(text)
                self.store.execute("INSERT OR REPLACE INTO boards VALUES(?,?,?)",(self.channel_id,msg.id,text))
        except (OSError, ValueError, discord.HTTPException) as error:
            logging.warning("Paper feed or Discord unavailable: %s",error)

    @publish.before_loop
    async def await_ready(self):
        await self.wait_until_ready()


def build(channel_id):
    client=WaveClient(channel_id)

    @client.tree.command(name="stats",description="Show the Aahil Wave public paper scoreboard")
    async def stats(interaction: discord.Interaction):
        await interaction.response.send_message(board_text(client.store))

    @client.tree.command(name="open",description="List pending and filled paper signals")
    async def opened(interaction: discord.Interaction):
        rows=[f"{k} {s['status']} • entry {price(s['entry'])} • stop {price(s['entry'] if s['status']=='be_armed' else s['stop'])}"
              for k,s in states(client.store).items() if s["status"] in ACTIVE]
        await interaction.response.send_message("\n".join(rows) or "No open paper signals.")
    return client


if __name__=="__main__":
    build(int(os.environ["DISCORD_CHANNEL_ID"])).run(os.environ["DISCORD_BOT_TOKEN"])
