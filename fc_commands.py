import discord
from discord import app_commands
from discord.ext import commands
import re
import pickle
import logging

from typing import Literal, Dict, Tuple

FC_MAP = {}


def is_fc(fc: str):
    return re.match("^[0-9]{4}-[0-9]{4}-[0-9]{4}(-2)?$", fc.strip()) is not None


class FCCog(commands.Cog):
    fc_group = app_commands.Group(name="fc",
                                  description="Show, set, or remove your FC",
                                  default_permissions=discord.Permissions(permissions=0))

    @fc_group.command(name="show", description="Send your FC")
    async def send_fc(self, interaction: discord.Interaction):
        if interaction.user.id in FC_MAP:
            await interaction.response.send_message(FC_MAP[interaction.user.id])
        else:
            await interaction.response.send_message(f"Use `/fc set` to set your FC.", ephemeral=True)

    @fc_group.command(name="set", description="Set your FC")
    @app_commands.describe(fc="Your FC")
    async def set_fc(self, interaction: discord.Interaction, fc: str):
        if not is_fc(fc):
            await interaction.response.send_message(f"Your FC must be in the following format (each x represents a "
                                                    f"digit): `xxxx-xxxx-xxxx`", ephemeral=True)
        else:
            FC_MAP[interaction.user.id] = fc
            save_data()
            await interaction.response.send_message(f"I have set your FC to {fc}", ephemeral=True)

    @fc_group.command(name="remove", description="Remove your FC")
    async def view_category(self, interaction: discord.Interaction):
        if interaction.user.id in FC_MAP:
            FC_MAP.pop(interaction.user.id)
            save_data()
        await interaction.response.send_message(f"I have deleted your FC", ephemeral=True)


async def setup(bot):
    await bot.add_cog(FCCog(bot))


def save_data():
    to_dump = {"FC_MAP": FC_MAP}
    with open("fc_data_pkl", "wb") as f:
        pickle.dump(to_dump, f)


def load_data():
    try:
        with open("fc_data_pkl", "rb") as f:
            to_load = pickle.load(f)
            FC_MAP.clear()
            FC_MAP.update(to_load["FC_MAP"])
    except Exception as e:
        logging.critical("Failed to load fc pickle:")
        logging.critical(e)
