import datetime
import typing
import discord

class TooManyPlayers(Exception):
    pass


class Player:

    def __init__(self,
                 name: str,
                 mmr: int,
                 lr: int,
                 time_queued: datetime.datetime,
                 can_host: bool,
                 drop_warned: bool,
                 queue_channel_id: int,
                 discord_id: int,
                 last_active: datetime.datetime):
        self.name = name
        self.mmr = mmr
        self.lr = lr
        self.time_queued = time_queued
        self.can_host = can_host
        self.drop_warned = drop_warned
        self.queue_channel_id = queue_channel_id
        self.discord_id = discord_id
        self.last_active = last_active

    def update_active_time(self):
        self.last_active = datetime.datetime.now()

    def get_queue_key(self):
        return self.name.lower()

    @staticmethod
    def discord_user_get_queue_key(user: discord.User):
        return user.display_name.lower()

    @staticmethod
    def get_queue_key_from_player_name(name: str, queue):
        name = name.lower()
        for queued in queue.values():
            if isinstance(queued, Group):
                for player in queued.get_players():
                    if player.name.lower() == name:
                        return player.get_queue_key()
            elif isinstance(queued, Player):
                if player.name.lower() == name:
                    return player.get_queue_key()



class Group:
    MAX_PLAYERS = 2
    GROUP_ID = 1

    def __init__(self, owner: Player):
        self._group = [owner]
        self.group_id = Group.GROUP_ID
        Group.GROUP_ID += 1

    def add_to_group(self, player: Player):
        if len(self._group) >= Group.MAX_PLAYERS:
            raise TooManyPlayers()
        self._group.append(player)

    def remove_from_group(self, player: Player):
        in_group = any(p.disord_id == player.discord_id for p in self._group)
        self._group = [p for p in self._group if p.disord_id != player.discord_id]
        return in_group

    def total_players(self):
        return len(self._group)

    def get_players(self):
        return self._group


