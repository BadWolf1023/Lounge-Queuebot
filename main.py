import asyncio
import random
from typing import Literal, Dict, Tuple, List, Optional, Union, Any
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

import game_queue
from config import TOKEN
import simulation
import shared
import rating
import logging
import datetime
import pickle
import algorithm
import fc_commands
from collections import defaultdict
import itertools
import test_rooms
import unittest

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

RT_QUEUE_CATEGORY = None
CT_QUEUE_CATEGORY = None
RT_QUEUE_CHANNELS = set()
CT_QUEUE_CHANNELS = set()

finished_on_ready = False
rooms = []
to_restart = []

RT_QUEUE = game_queue.Queue()
CT_QUEUE = game_queue.Queue()

def channel_is_free(channel_id: int):
    if channel_id is None:
        return False
    return all(r.room_channel_id != channel_id for r in rooms)


def get_queue(ladder_type: str | int):
    if ladder_type == shared.RT_LADDER:
        return RT_QUEUE
    elif ladder_type == shared.CT_LADDER:
        return CT_QUEUE
    elif ladder_type in RT_QUEUE_CHANNELS:
        return RT_QUEUE
    elif ladder_type in CT_QUEUE_CHANNELS:
        return CT_QUEUE


def get_queue_channels(ladder_type: str):
    if ladder_type == shared.RT_LADDER:
        return RT_QUEUE_CHANNELS
    elif ladder_type == shared.CT_LADDER:
        return CT_QUEUE_CHANNELS


class Room:
    ROOM_EXPIRATION_TIME = datetime.timedelta(minutes=5)
    ROOM_WARN_TIME = datetime.timedelta(minutes=3)
    ROOM_EXTENSION_TIME = datetime.timedelta(minutes=5)
    MAX_ROOM_ACCESS_TIME = datetime.timedelta(minutes=6)

    def __init__(self, players: List[game_queue.Player], ladder_type: str):
        self.players = list(players)
        self.ladder_type = ladder_type
        self.room_channel_id: int = None
        self.winning_vote = None
        self.votes = {}
        self.start_time = datetime.datetime.now()
        self.expiration_time = self.start_time + Room.ROOM_EXPIRATION_TIME
        self.expiration_warning_sent = False
        self.teams: List[List[game_queue.Player]] = None
        self.finished = False
        self.host_str = "No one queued as a host."

        # Used for restarting the bot
        self.changed_visibility = False
        self.finished_start = False

    def get_category_channel(self) -> discord.CategoryChannel | None:
        category_id = RT_QUEUE_CATEGORY if self.ladder_type == shared.RT_LADDER else CT_QUEUE_CATEGORY
        return bot.get_channel(category_id)

    def get_room_channel(self) -> discord.TextChannel | None:
        return bot.get_channel(self.room_channel_id)

    def expires_soon(self) -> bool:
        return (datetime.datetime.now() + Room.ROOM_WARN_TIME) >= self.expiration_time

    def extend_goes_past_max_time(self) -> bool:
        return (self.expiration_time + Room.ROOM_EXTENSION_TIME) > (self.start_time + Room.MAX_ROOM_ACCESS_TIME)

    def minutes_to_expiration(self) -> int:
        return int((self.expiration_time - datetime.datetime.now()).seconds / 60)

    def extend_(self):
        self.expiration_time = self.expiration_time + Room.ROOM_EXTENSION_TIME
        self.expiration_warning_sent = False

    def is_expired(self) -> bool:
        return datetime.datetime.now() > self.expiration_time

    def should_warn_expiration(self):
        return not self.expiration_warning_sent and self.expires_soon()

    async def warn_expiration(self):
        if self.get_room_channel() is not None:
            self.expiration_warning_sent = True
            await self.get_room_channel().send(
                f"**Players will lose access to this channel in {int(Room.ROOM_WARN_TIME.seconds / 60)} minutes.** Use slash command `/extend` for a {int(Room.ROOM_EXTENSION_TIME.seconds / 60)} minute extension.")

    def make_even_teams(self, lineup, num_teams=2):
        """Brute forces all combinations of teams. Be careful... 12 choose 6 = 954, which is OK"""
        lineup = set(lineup)
        self.teams = []

        def difference_of_sums(team):
            team = set(team)
            second_team = lineup.difference(team)
            return abs(sum(algorithm.get_mmr(p1) for p1 in team) - sum(algorithm.get_mmr(p2) for p2 in second_team))

        most_even_team = min(itertools.combinations(lineup, len(lineup) // num_teams), key=difference_of_sums)
        self.teams.append(list(most_even_team))
        self.teams.append(list(lineup.difference(most_even_team)))

    def make_teams(self):
        lineup = self.players[:algorithm.LINEUP_SIZE]
        random.shuffle(lineup)
        step_map = {"FFA": 1, "2v2": 2, "3v3": 3, "4v4": 4, "6v6": 1}
        step = step_map[self.winning_vote]
        self.teams = []
        if self.winning_vote == "6v6":
            self.make_even_teams(lineup)
        else:
            for i in range(0, len(lineup), step):
                self.teams.append(lineup[i:i + step])
        self.teams.sort(key=get_team_average_mmr, reverse=True)

    def randomize_host(self):
        hosts = [p for p in self.players[:algorithm.LINEUP_SIZE] if p.can_host]
        if len(hosts) > 0:
            random.shuffle(hosts)
            result = "Host order:"
            for list_num, p in enumerate(hosts, start=1):
                fc = fc_commands.get_fc(p.discord_id)
                result += f"\n{list_num}. {p.name}"
                result += '' if fc is None else f" ({fc})"
            self.host_str = result

    async def send_teams_at_start(self):
        header = f"Winner: {self.winning_vote}"
        await self.send_teams(header)

    async def send_teams(self, header=""):
        await self.get_room_channel().send(self.get_teams_str(header=header) + f"\n\n{self.host_str}")

    def get_teams_str(self, header="") -> str:
        results = [] if len(header) == 0 else [header]
        for team_number, team in enumerate(self.teams, start=1):
            players_str = ", ".join(p.name for p in team)
            results.append(f"{team_number}. {players_str} ({get_team_average_mmr(team)} MMR)")
        return "\n".join(results)

    def mention_all_players_str(self) -> str:
        return ", ".join(mention(p) for p in self.players)

    async def begin_event(self):
        category_channel = self.get_category_channel()
        if category_channel is None:
            await send_message_to_all_queue_channels(
                f"Cannot begin event. Admins have not set the category channel for {self.ladder_type.upper()}s.",
                self.ladder_type)
            return

        obtained = await self.obtain_channel(category_channel)
        if not obtained:
            await send_message_to_all_queue_channels(
                f"Cannot begin event. There are no available channels to put a lineup in.",
                self.ladder_type)
            return

        await self.change_player_visibility(view=True)
        self.changed_visibility = True
        await self.cast_vote()

    async def after_vote(self, winning_vote, votes):
        self.winning_vote = winning_vote
        self.votes.update(votes)
        self.make_teams()
        self.randomize_host()
        await self.send_teams_at_start()
        self.finished_start = True

    async def send_vote_notification(self):
        await self.get_room_channel().send(
            f"{self.mention_all_players_str()} the event has started. Cast your vote below.")

    async def cast_vote(self):
        await self.send_vote_notification()
        voting_view = Voting(self.players, self.after_vote, timeout=Voting.get_voting_seconds())
        voting_view.message = await self.get_room_channel().send(view=voting_view)

    async def obtain_channel(self, category_channel: discord.CategoryChannel):
        for channel in category_channel.text_channels:
            if channel_is_free(channel.id):
                self.room_channel_id = channel.id
                break
        return self.room_channel_id is not None

    async def end(self):
        if self.finished is False:
            await self.change_player_visibility(view=False)
            await self.get_room_channel().send("The event has ended.")
            self.finished = True

    async def change_player_visibility(self, view=True):
        category_channel = bot.get_channel(self.room_channel_id).category
        overwrites = {
            category_channel.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            category_channel.guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        for player in self.players:
            discord_member = bot.get_user(player.discord_id)
            if discord_member is not None:
                overwrites[discord_member] = discord.PermissionOverwrite(view_channel=view)

        final_text_channel_overwrites = category_channel.overwrites.copy()
        overwrites.update(final_text_channel_overwrites)
        await bot.get_channel(self.room_channel_id).edit(overwrites=overwrites)


class AdminCog(commands.Cog):
    def __init__(self, bot_: commands.Bot) -> None:
        self.bot = bot_

    channel_group = app_commands.Group(name="queueing-channels",
                                       description="Administrative commands to add, remove, or view channels that Queuebot monitors for queueing",
                                       default_permissions=discord.Permissions(permissions=0))

    queueing_category_group = app_commands.Group(name="category",
                                                 description="Administrative commands to view or set the category that channels are made in for gathered lineups",
                                                 default_permissions=discord.Permissions(permissions=0))

    @queueing_category_group.command(name="set", description="Set a category that text channels will be created under")
    @app_commands.describe(category="Category that text channels will be created under for lineups that gather",
                           rt_or_ct="Will this category be for RTs or CTs?")
    async def set_category(self, interaction: discord.Interaction,
                           category: discord.CategoryChannel,
                           rt_or_ct: Literal[shared.RT_LADDER, shared.CT_LADDER]):
        if rt_or_ct == shared.RT_LADDER:
            global RT_QUEUE_CATEGORY
            RT_QUEUE_CATEGORY = category.id
        else:
            global CT_QUEUE_CATEGORY
            CT_QUEUE_CATEGORY = category.id

        await interaction.response.send_message(
            f"Text channels will be created under the {category.mention} category for lineups that gather for {rt_or_ct}s.")

    @queueing_category_group.command(name="view",
                                     description="Display the set categories that text channels will be created under when lineups gather")
    async def view_category(self, interaction: discord.Interaction):
        rt_category = bot.get_channel(RT_QUEUE_CATEGORY)
        ct_category = bot.get_channel(CT_QUEUE_CATEGORY)

        rt_category_mention = "Not set" if rt_category is None else rt_category.mention
        ct_category_mention = "Not set" if ct_category is None else ct_category.mention

        to_send = f"Lineups gathered for RTs will have their rooms created under the following category: {rt_category_mention}\n" + \
                  f"Lineups gathered for CTs will have their rooms created under the following category: {ct_category_mention}"
        await interaction.response.send_message(to_send)

    @channel_group.command(name="add", description="Specify a channel that players can queue in")
    @app_commands.describe(channel="In what channel is queueing to be allowed?",
                           rt_or_ct="Will queueing here be for RTs or CTs?")
    async def add_channel(self, interaction: discord.Interaction,
                          channel: discord.TextChannel,
                          rt_or_ct: Literal[shared.RT_LADDER, shared.CT_LADDER]):
        if channel.id in RT_QUEUE_CHANNELS:
            await interaction.response.send_message(
                f"I am already {channel.mention} is already being monitored for RTs")
        elif channel.id in CT_QUEUE_CHANNELS:
            await interaction.response.send_message(f"{channel.mention} is already being monitored for CTs")
        else:
            queue_channels = get_queue_channels(rt_or_ct)
            queue_channels.add(channel.id)
            await interaction.response.send_message(
                f"Players who queue in {channel.mention} will now be added to the "
                f"{rt_or_ct} queue.")

    @channel_group.command(name="remove",
                           description="Specify a channel that players are not allowed to queue in anymore")
    @app_commands.describe(channel="In what channel is queueing no longer allowed?")
    async def remove_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if channel.id in RT_QUEUE_CHANNELS:
            RT_QUEUE_CHANNELS.remove(channel.id)
            await interaction.response.send_message(
                f"I will not allow queueing in {channel.mention} for RTs anymore")
        elif channel.id in CT_QUEUE_CHANNELS:
            CT_QUEUE_CHANNELS.remove(channel.id)
            await interaction.response.send_message(
                f"I will not allow queueing in {channel.mention} for CTs anymore")
        else:
            await interaction.response.send_message(
                f"I wasn't allowing players to queue in this channel in the first place.")

    @channel_group.command(name="view", description="Display all channels that players can queue in")
    async def view_channels(self, interaction: discord.Interaction):
        rt_channels = []
        ct_channels = []
        for channel_id in RT_QUEUE_CHANNELS:
            rt_channels.append(bot.get_channel(channel_id))
        for channel_id in CT_QUEUE_CHANNELS:
            ct_channels.append(bot.get_channel(channel_id))

        to_send = f"Queueing for RTs is allowed in the following channels: " \
                  f"{', '.join(rtc.mention for rtc in rt_channels)}\n" \
                  f"Queueing for CTs is allowed in the following channels:{', '.join(ctc.mention for ctc in ct_channels)}"
        await interaction.response.send_message(to_send)


class TestingCog(commands.Cog):
    def __init__(self, bot_: commands.Bot) -> None:
        self.bot = bot_

    @app_commands.command(name="add", description="TESTING ONLY: Add players to the queue.")
    @app_commands.describe(players="Specify which players to add to the queue. Seperate player names with a comma.")
    @app_commands.default_permissions()
    async def add_players(self, interaction: discord.Interaction, players: str):
        if interaction.channel_id not in RT_QUEUE_CHANNELS and interaction.channel_id not in CT_QUEUE_CHANNELS:
            await interaction.response.send_message(f"Queueing is not allowed in this channel.", ephemeral=True)
            return

        await interaction.response.defer()
        ladder = shared.RT_LADDER if interaction.channel_id in RT_QUEUE_CHANNELS else shared.CT_LADDER

        player_names = players.split(",")
        results = []
        for player in player_names:
            update_player_activity(player.strip(), interaction.channel.id)
            result = await add_player_to_queue(interaction, player.strip(), False, ladder, send_message=False)
            results.append(result)
        await send_queue_data_file(interaction, results, "results.txt")

    @app_commands.command(name="debug-queue", description="Outputs scores of all lineups")
    @app_commands.default_permissions()
    async def debug_queue(self, interaction: discord.Interaction):
        await interaction.channel.send("This command does not work currently.")
        await interaction.response.defer()
        queue_datas = simulation.get_lineup_debug_str(list(RT_QUEUE.values()), list(CT_QUEUE.values()))
        await send_queue_data_file(interaction, queue_datas, "queue_data.txt")


async def setup(bot_: commands.Bot) -> None:
    await bot_.add_cog(AdminCog(bot_))
    await bot_.add_cog(TestingCog(bot_))
    await fc_commands.setup(bot_)


@bot.event
async def on_ready():
    global finished_on_ready
    print("Logging in...")

    if not finished_on_ready:
        await setup(bot)
        if not shared.TESTING:
            bot.tree.remove_command("add")
            bot.tree.remove_command("mllu-text-simulation")
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} commands: {synced}")
            pull_mmr.start()
            run_routines.start()
            restart_rooms()
        except Exception as e:
            print(e)

    finished_on_ready = True
    print(f"Logged in as {bot.user}")


async def add_player_to_queue(interaction: discord.Interaction, player_name: str, can_host: bool, ladder_type: str,
                              send_message=True):
    queue = get_queue(ladder_type)
    # Logic for if the player is already in the queue:
    potential_addition = game_queue.Player.name_to_partial_player(player_name)
    player = queue.get_player(potential_addition)
    if player is not None:
        msg = f"{player.name} is already in the {ladder_type.upper()} queue."
        if player.can_host != can_host:
            msg = f"{player.name} is {'now' if can_host else 'no longer'} a host."
            player.can_host = can_host
        if send_message:
            await interaction.response.send_message(msg)
        return msg

    # Logic for when the player is not in the queue...
    #   Pull their rating and update their name
    player_rating = rating.get_player_rating(player_name, ladder_type)
    if shared.TESTING:
        player_name = player_rating[0] if player_rating is not None else player_name
    else:
        player_name = interaction.user.display_name

    # Logic for when the rating for the player could not be found
    if player_rating is None:
        msg = f"No {ladder_type.upper()} rating found for {player_name}. Not allowed to queue."
        if send_message:
            await interaction.response.send_message(msg)
        return msg

    cur_time = datetime.datetime.now()
    queue.add_to_queue(game_queue.Player(name=player_name,
                               mmr=player_rating[2],
                               lr=player_rating[3],
                               time_queued=cur_time,
                               can_host=can_host,
                               drop_warned=False,
                               queue_channel_id=interaction.channel_id,
                               discord_id=interaction.user.id,
                               last_active=cur_time,
                               discord_member=interaction.user))
    msg = f"{player_name} has joined the {ladder_type.upper()} queue."
    if send_message:
        await interaction.response.send_message(msg)
    return msg


async def remove_player_from_queue(interaction: discord.Interaction,
                                   player_name: str,
                                   queue: game_queue.Queue,
                                   reason: str = "dropped"):
    ladder_type = shared.RT_LADDER if queue is RT_QUEUE else shared.CT_LADDER
    partial_player = game_queue.Player.name_to_partial_player(player_name)
    player = queue.remove_from_queue(partial_player)
    if player is None:
        await interaction.response.send_message(f"{player_name} is not in the {ladder_type.upper()} queue.")
    else:
        await interaction.response.send_message(
        f"Removed {player.name} from the {ladder_type.upper()} queue due to: {reason}")


async def list_queue(interaction: discord.Interaction, ladder_type: str):
    queue = get_queue(ladder_type)
    if len(queue) == 0:
        await interaction.response.send_message(f"No players in the {ladder_type.upper()} queue.")
        return
    result = f"{ladder_type.upper()} queue:"
    for index, (group_number, player) in enumerate(queue.get_players_with_group_numbers(), 1):
        result += f"\n{index}. {player.name} ({player.mmr} MMR)"
        if group_number is not None:
            result += f" (group #{group_number})"
        if player.can_host:
            result += " - host"

    await interaction.response.send_message(result)


@bot.tree.command(name="can", description="Join the queue")
@app_commands.describe(host="Can you host?")
async def can(interaction: discord.Interaction,
              host: Literal["No", "Yes"] = "No"):
    can_host = host == "Yes"
    update_player_activity(interaction.user, interaction.channel.id)

    if interaction.channel_id in RT_QUEUE_CHANNELS:
        await add_player_to_queue(interaction, interaction.user.display_name, can_host,
                                  shared.RT_LADDER)
    elif interaction.channel_id in CT_QUEUE_CHANNELS:
        await add_player_to_queue(interaction, interaction.user.display_name, can_host,
                                  shared.CT_LADDER)
    else:
        await interaction.response.send_message(f"Queueing is not allowed in this channel.", ephemeral=True)


@bot.tree.command(name="drop", description="Leave the queue")
async def drop(interaction: discord.Interaction):
    queue = get_queue(interaction.channel_id)
    if queue is None:
        await interaction.response.send_message(f"Queueing is not allowed in this channel.", ephemeral=True)
    else:
        await remove_player_from_queue(interaction, interaction.user.display_name, queue)



@bot.tree.command(name="remove", description="Remove a player from the queue")
@app_commands.describe(player="Specify which player to remove from the queue")
@app_commands.default_permissions()
async def remove(interaction: discord.Interaction, player: str):
    update_player_activity(interaction.user, interaction.channel.id)
    queue = get_queue(interaction.channel_id)
    if queue is None:
        return await interaction.response.send_message(f"Queueing is not allowed in this channel.", ephemeral=True)
    await remove_player_from_queue(interaction, player, queue, reason="Moderator removed")




@bot.tree.command(name="extend",
                  description=f"Extend channel access for players by {int(Room.ROOM_EXTENSION_TIME.seconds / 60)} minutes")
async def extend_(interaction: discord.Interaction):
    for room in rooms:
        if room.get_room_channel() is not None and room.room_channel_id == interaction.channel_id:
            if room.expires_soon():
                if room.extend_goes_past_max_time():
                    await interaction.response.send_message(f"Cannot extend player access. The maximum time players "
                                                            f"can view this channel has been reached.", ephemeral=True)
                else:
                    room.extend_()
                    await interaction.response.send_message(f"Channel access for players has been extended by "
                                                            f"{int(Room.ROOM_EXTENSION_TIME.seconds / 60)} minutes.")
            else:
                await interaction.response.send_message(f"Players still have access for {room.minutes_to_expiration()}"
                                                        f" minutes, so your request has been ignored.", ephemeral=True)
            break
    else:
        await interaction.response.send_message(f"This is not a room channel.", ephemeral=True)


@remove.autocomplete('player')
async def player_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    queue = get_queue(interaction.channel_id)
    if queue is None:
        return []
    return [app_commands.Choice(name=player.name,
                                value=player.name)
            for player in queue.get_players() if current.lower() in player.name.lower()
            ]


players_group = app_commands.Group(name="group",
                                   description="Playing with friends")


@players_group.command(name="add", description="Ask a player to join your group for queueing")
@app_commands.describe(player="The player to join your group")
async def group_add(interaction: discord.Interaction, player: discord.Member):
    queue = get_queue(interaction.channel_id)
    groups = get_all_groups(queue)


@players_group.command(name="drop",
                       description="Drop from your group and play alone - does not drop you from the queue")
async def group_drop(interaction: discord.Interaction):
    rt_category = bot.get_channel(RT_QUEUE_CATEGORY)
    ct_category = bot.get_channel(CT_QUEUE_CATEGORY)

    rt_category_mention = "Not set" if rt_category is None else rt_category.mention
    ct_category_mention = "Not set" if ct_category is None else ct_category.mention

    to_send = f"Lineups gathered for RTs will have their rooms created under the following category: {rt_category_mention}\n" + \
              f"Lineups gathered for CTs will have their rooms created under the following category: {ct_category_mention}"
    await interaction.response.send_message(to_send)


@bot.tree.command(name="list", description="List players in the queue")
@app_commands.checks.cooldown(rate=1, per=30.0, key=lambda x: x.channel_id)
async def list_command(interaction: discord.Interaction):
    update_player_activity(interaction.user, interaction.channel.id)
    if interaction.channel_id in RT_QUEUE_CHANNELS:
        await list_queue(interaction, shared.RT_LADDER)
    elif interaction.channel_id in CT_QUEUE_CHANNELS:
        await list_queue(interaction, shared.CT_LADDER)
    else:
        await interaction.response.send_message(f"Queueing is not allowed in this channel.", ephemeral=True)


@list_command.error
async def cool_down_exception(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        retry_seconds = int(error.retry_after) + 1
        error_str = f"This command is on cooldown. Try again after {retry_seconds} " \
                    f"second{'' if retry_seconds == 1 else 's'}."
        await interaction.response.send_message(error_str, ephemeral=True)
    else:
        await interaction.response.send_message(f"Contact Bad Wolf, this error should not have occurred:\n{error}")


@bot.tree.command(name="mllu-text-simulation",
                  description="Input the text from MogiBot's message in #mogilist-lu to computer lineup scores")
@app_commands.default_permissions()
async def mllu_text_simulation(interaction: discord.Interaction):
    await interaction.response.send_modal(MLLUTextModal())


@bot.tree.command(name="save", description="Save data internally")
@app_commands.default_permissions()
async def save(interaction: discord.Interaction):
    save_data()
    await interaction.response.send_message("Saved.")


class MLLUTextModal(ui.Modal, title="MogiBot's #mogilist-lu message in Lounge"):
    answer = ui.TextInput(label="#mogilist-lu text", style=discord.TextStyle.long, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        queue_str_data = simulation.get_simulation_str(self.answer.value)
        await send_queue_data_file(interaction, queue_str_data, "mllu_simulation.txt")


async def send_queue_data_file(interaction: discord.Interaction, queue_str_data: Tuple, file_name: str):
    with open(file_name, "w") as f:
        for str_data in queue_str_data:
            f.write(str_data)
            f.write("\n\n")
    with open(file_name, "rb") as f:
        await interaction.followup.send(file=discord.File(f))


async def run_drop_warn(ladder_type: str):
    current_time = datetime.datetime.now()
    warn_time = datetime.timedelta(minutes=shared.WARN_DROP_TIME)
    drop_time = datetime.timedelta(minutes=shared.AUTO_DROP_TIME)
    queue = get_queue(ladder_type)
    channel_ids = RT_QUEUE_CHANNELS if ladder_type == shared.RT_LADDER else CT_QUEUE_CHANNELS

    # Drop players who have been warned, are no longer active, and are beyond the drop time
    to_drop = []
    for player in queue:
        if (current_time - queue[player].last_active) >= drop_time and queue[player].drop_warned:
            to_drop.append(queue[player])

    if len(to_drop) > 0:
        builder_str = f"Removed {', '.join(p.name for p in to_drop)} due to inactivity."
        for player in to_drop:
            if player.get_queue_key() in queue:
                queue.pop(player.get_queue_key())

        channels_to_notify: List[discord.TextChannel] = [bot.get_channel(channel_id) for channel_id in channel_ids]
        for channel in channels_to_notify:
            await channel.send(builder_str)

    # Warn players about dropping because they have been inactive
    to_warn: List[game_queue.Player] = []
    for player in queue:
        if (current_time - queue[player].last_active) >= warn_time and not queue[player].drop_warned:
            to_warn.append(queue[player])
    players_to_warn_by_channel = defaultdict(list)
    for player in to_warn:
        player.drop_warned = True
        players_to_warn_by_channel[player.queue_channel_id].append(player)
    for channel_id, players in players_to_warn_by_channel.items():
        channel = bot.get_channel(channel_id)
        builder_str = f"{', '.join(mention(p) for p in players)} you will be dropped from the queue in" \
                      f"{shared.AUTO_DROP_TIME - shared.WARN_DROP_TIME} minutes due to inactivity." \
                      f"Please type something in the chat to remain in the queue."
        await channel.send(builder_str)


async def drop_warn():
    await run_drop_warn(shared.RT_LADDER)
    await run_drop_warn(shared.CT_LADDER)


def save_data():
    to_dump = {"RT_QUEUE_CHANNELS": RT_QUEUE_CHANNELS,
               "CT_QUEUE_CHANNELS": CT_QUEUE_CHANNELS,
               "RT_QUEUE": RT_QUEUE,
               "CT_QUEUE": CT_QUEUE,
               "RT_QUEUE_CATEGORY": RT_QUEUE_CATEGORY,
               "CT_QUEUE_CATEGORY": CT_QUEUE_CATEGORY,
               "rooms": rooms}
    with open("main_pkl", "wb") as f:
        pickle.dump(to_dump, f)
    rating.save_data()
    fc_commands.save_data()


def restart_rooms():
    for room in to_restart:
        print(room)
        if not room.finished_start:
            if not room.changed_visibility:
                asyncio.create_task(room.begin_event())
            else:
                asyncio.create_task(room.cast_vote())
    to_restart.clear()


def add_rooms_restart():
    for room in rooms:
        if not room.finished_start:
            to_restart.append(room)


def load_data():
    try:
        with open("main_pkl", "rb") as f:
            to_load = pickle.load(f)
            RT_QUEUE_CHANNELS.clear()
            RT_QUEUE_CHANNELS.update(to_load["RT_QUEUE_CHANNELS"])
            CT_QUEUE_CHANNELS.clear()
            CT_QUEUE_CHANNELS.update(to_load["CT_QUEUE_CHANNELS"])
            RT_QUEUE.clear()
            RT_QUEUE.extend(to_load["RT_QUEUE"])
            CT_QUEUE.clear()
            CT_QUEUE.extend(to_load["CT_QUEUE"])
            global RT_QUEUE_CATEGORY
            RT_QUEUE_CATEGORY = to_load["RT_QUEUE_CATEGORY"]
            global CT_QUEUE_CATEGORY
            CT_QUEUE_CATEGORY = to_load["CT_QUEUE_CATEGORY"]
            rooms.clear()
            rooms.extend(to_load["rooms"])
            add_rooms_restart()
    except Exception as e:
        logging.critical("Failed to load main pickle:")
        logging.critical(e)
    rating.load_data()
    fc_commands.load_data()
    print("All data loaded.")


def update_player_activity(member: discord.Member, channel_id: int):
    queue = get_queue(channel_id)
    if queue is None:
        return
    partial_player = game_queue.Player.discord_member_to_partial_player(member)
    actual_player = queue.get_player(partial_player)
    if actual_player is not None:
        actual_player.update_active_time()


@bot.event
async def on_message(message: discord.Message):
    update_player_activity(message.author, message.channel.id)


def update_queued_player_ratings(ladder_type: str):
    queue = get_queue(ladder_type)
    for player in queue.get_players():
        player_rating = rating.get_player_rating(player.get_queue_key(), ladder_type)
        if player_rating is not None:
            player.mmr = player_rating[0]
            player.lr = player_rating[1]


@tasks.loop(minutes=30, reconnect=True)
async def pull_mmr():
    await rating.pull_mmr_data(shared.RT_LADDER)
    update_queued_player_ratings(shared.RT_LADDER)
    await rating.pull_mmr_data(shared.CT_LADDER)
    update_queued_player_ratings(shared.CT_LADDER)
    logging.info(f"Pulled mmr")


def remove_all_players(players: List[game_queue.Player], ladder_type: str):
    queue = get_queue(ladder_type)
    for player in players:
        queue.pop(player.get_queue_key(), None)


async def send_message_to_all_queue_channels(message: str, ladder_type: str):
    channel_ids = RT_QUEUE_CHANNELS if ladder_type == shared.RT_LADDER else CT_QUEUE_CHANNELS
    channels: List[discord.TextChannel] = [bot.get_channel(channel_id) for channel_id in channel_ids]
    for channel in channels:
        await channel.send(message)


async def form_lineups(ladder_type: str):
    return
    channel_ids = RT_QUEUE_CHANNELS if ladder_type == shared.RT_LADDER else CT_QUEUE_CHANNELS
    channels: List[discord.TextChannel] = [bot.get_channel(channel_id) for channel_id in channel_ids]
    to_edit = []
    for channel in channels:
        to_edit.append((await channel.send("Looking for rooms that can be created...")))

    queue = get_queue(ladder_type)
    formed_lineup = False
    while True:
        best_lineups = algorithm.get_best_lineup_for_each_player(list(queue.values()))
        sorted_by_score = sorted(best_lineups, key=algorithm.compute_lineup_score, reverse=True)
        if len(sorted_by_score) > 0:
            best_lineup = sorted_by_score[0]
            if algorithm.compute_lineup_score(best_lineup) >= algorithm.SCORE_THRESHOLD:
                # pop room for the players
                formed_lineup = True
                event_str = "an" if ladder_type == shared.RT_LADDER else "a"
                text_str = f"A room has formed. Starting {event_str} {ladder_type.upper()} event for " \
                           f"`{', '.join(p.name for p in best_lineup)}`..."
                my_str = simulation.get_best_lineups_str([best_lineup], ladder_type, header=False)

                # remove all players from both queues
                remove_all_players(best_lineup, shared.RT_LADDER)
                remove_all_players(best_lineup, shared.CT_LADDER)

                await send_message_to_all_queue_channels(text_str + "\n" + my_str, ladder_type)

                cur_room = Room(best_lineup, ladder_type)
                rooms.append(cur_room)

                await cur_room.begin_event()

            else:
                break
        else:
            break

    if formed_lineup is False:
        for msg in to_edit:
            await msg.edit(content="No rooms can be formed.")


async def delete_expired_rooms():
    # This function is intentionally written this way to avoid race conditions with other asynchronous code
    to_end = []
    index_removal = []
    for room_index, room in enumerate(rooms):
        if room.is_expired():
            to_end.append(room)
            index_removal.append(room_index)

    for index in index_removal[::-1]:
        rooms.pop(index)

    for r in to_end:
        await r.end()


async def warn_almost_expired_rooms():
    for room in rooms:
        if room.should_warn_expiration():
            await room.warn_expiration()


@tasks.loop(minutes=1, reconnect=True)
async def run_routines():
    try:
        await drop_warn()
        await form_lineups(ladder_type=shared.RT_LADDER)
        await form_lineups(ladder_type=shared.CT_LADDER)
        await delete_expired_rooms()
        await warn_almost_expired_rooms()
    except Exception as e:
        logging.critical("Exception occurred in run_routine loop:")
        logging.exception(e)
        try:
            all_queue_channels = RT_QUEUE_CHANNELS | CT_QUEUE_CHANNELS
            for channel_id in all_queue_channels:
                await bot.get_channel(channel_id).send(
                    f"Tell Bad Wolf to check the logs. The following error occurred: {e}")
        except Exception as f:
            logging.critical("Exception occurred in run_routine loop queue channel sending:")
            logging.exception(f)


class QueueWithFriend(discord.ui.View):
    RESPONSE_TIMEOUT = datetime.timedelta(minutes=5)

    @staticmethod
    def get_response_timeout_seconds():
        return QueueWithFriend.RESPONSE_TIMEOUT.seconds

    def __init__(self, me: game_queue.Player, friend: game_queue.Player, ladder_type: str, on_finish_callback, **kwargs):
        self.me = me
        self.friend = friend
        self.responded = False
        asyncio.create_task(self.response_timeout())
        super().__init__(**kwargs)

    def remove_me_from_friends(self):
        pass

    @discord.ui.button(label='Yes', style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.yes_button(interaction, button, "FFA")

    @discord.ui.button(label='No', style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.no_button(interaction, button, "FFA")

    async def response_timeout(self):
        await asyncio.sleep(QueueWithFriend.get_response_timeout_seconds())
        if not self.responded:
            self.responded = True
            self.stop()
            # TODO: Remove player from original player's friends

    def is_valid_voter(self, player_key: Any) -> bool:
        return any(player.get_queue_key() == player_key for player in self.players)


    async def vote_button(self, interaction: discord.Interaction, button: discord.ui.Button, original_label: str):
        if not self.voting:
            return

        voter_queue_key = game_queue.Player.discord_member_to_partial_player(interaction.user).get_queue_key()
        if not self.is_valid_voter(voter_queue_key):
            await interaction.response.defer()
            return

        self.place_vote(voter_queue_key, original_label)
        self.update_labels()
        if self.has_winner():
            self.voting = False
        await interaction.message.edit(view=self)
        await interaction.response.defer()

        if not self.voting:
            self.stop()
            await self.__on_finish_callback(self.get_winner(), self.votes)


class Voting(discord.ui.View):
    if shared.TESTING:
        VOTE_TIME = datetime.timedelta(seconds=30)
    else:
        VOTE_TIME = datetime.timedelta(minutes=2)

    @staticmethod
    def get_voting_seconds():
        return Voting.VOTE_TIME.seconds

    def __init__(self, players: List[game_queue.Player], on_finish_callback, **kwargs):
        self.votes = {"FFA": set(), "2v2": set(), "3v3": set(), "4v4": set(), "6v6": set()}
        self.players: List[game_queue.Player] = players
        self.voting = True
        self.__on_finish_callback = on_finish_callback
        asyncio.create_task(self.vote_timeout())
        super().__init__(**kwargs)

    async def vote_timeout(self):
        await asyncio.sleep(Voting.get_voting_seconds())
        if self.voting:
            self.voting = False
            self.stop()
            await self.__on_finish_callback(self.get_winner(), self.votes)

    def get_winner(self):
        winning_votes = []
        winning_counter = 0
        for vote, voters in self.votes.items():
            if len(voters) < winning_counter:
                continue
            elif len(voters) == winning_counter:
                winning_votes.append(vote)
            else:
                winning_votes.clear()
                winning_votes.append(vote)
                winning_counter = len(voters)

        return random.choice(winning_votes)

    def is_valid_voter(self, player_key: Any) -> bool:
        return any(player.get_queue_key() == player_key for player in self.players)

    def place_vote(self, player_key: Any, vote: str):
        for voters in self.votes.values():
            if player_key in voters:
                voters.remove(player_key)
        self.votes[vote].add(player_key)

    def update_labels(self):
        for vote_option, votes in self.votes.items():
            for child in self.children:
                if child.label.startswith(vote_option):
                    child.label = f"{vote_option} - {len(votes)}"
                    break

    def has_winner(self):
        for votes in self.votes.values():
            if len(votes) >= int((algorithm.LINEUP_SIZE + 1) / 2):  # if the majority voted for an option
                return True
        return False

    async def vote_button(self, interaction: discord.Interaction, button: discord.ui.Button, original_label: str):
        if not self.voting:
            return
        voter_queue_key = game_queue.Player.discord_member_to_partial_player(interaction.user).get_queue_key()

        if not self.is_valid_voter(voter_queue_key):
            await interaction.response.defer()
            return

        self.place_vote(voter_queue_key, original_label)
        self.update_labels()
        if self.has_winner():
            self.voting = False
        await interaction.message.edit(view=self)
        await interaction.response.defer()

        if not self.voting:
            self.stop()
            await self.__on_finish_callback(self.get_winner(), self.votes)

    @discord.ui.button(label='FFA - 0', style=discord.ButtonStyle.red)
    async def ffa(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.vote_button(interaction, button, "FFA")

    @discord.ui.button(label='2v2 - 0', style=discord.ButtonStyle.red)
    async def two_versus_two(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.vote_button(interaction, button, "2v2")

    @discord.ui.button(label='3v3 - 0', style=discord.ButtonStyle.red)
    async def three_versus_three(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.vote_button(interaction, button, "3v3")

    @discord.ui.button(label='4v4 - 0', style=discord.ButtonStyle.red)
    async def four_versus_four(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.vote_button(interaction, button, "4v4")

    @discord.ui.button(label='6v6 - 0', style=discord.ButtonStyle.red)
    async def six_versus_six(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.vote_button(interaction, button, "6v6")


def get_team_average_lr(team: List[game_queue.Player]):
    return int(sum(p.lr for p in team) / len(team))


def get_team_average_mmr(team: List[game_queue.Player]):
    return int(sum(p.mmr for p in team) / len(team))

def mention(user: int | game_queue.Player):
    user_id = user.discord_id if isinstance(user, game_queue.Player) else user
    discord_member = bot.get_user(user_id)
    return f"<@{user_id}>" if discord_member is None else discord_member.mention


if __name__ == "__main__":
    load_data()
    if shared.RUN_UNIT_TESTS:
        test_rooms.set_room(Room)
        suite = unittest.TestLoader().loadTestsFromModule(test_rooms)
        # run all tests with verbosity
        unittest.TextTestRunner(verbosity=2).run(suite)

    bot.run(TOKEN, log_level=logging.INFO)
