import datetime
from typing import List, Tuple
import discord
import shared

class QueueExceptions(Exception):
    pass

class TooManyPlayers(QueueExceptions):
    pass

class GroupCombination(QueueExceptions):
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
                 last_active: datetime.datetime,
                 discord_member: discord.Member):
        self._name = name
        self.mmr = mmr
        self.lr = lr
        self.time_queued = time_queued
        self.can_host = can_host
        self.drop_warned = drop_warned
        self.queue_channel_id = queue_channel_id
        self.discord_id = discord_id
        self.last_active = last_active
        self.discord_member = discord_member

    @property
    def name(self):
        if not shared.TESTING:
            if self.discord_member is not None:
                return self.discord_member.display_name
        return self._name

    def update_activity(self):
        self.last_active = datetime.datetime.now()
        self.drop_warned = False

    def get_queue_key(self):
        return shared.utf8_to_ascii_mapping_name_fix(self.name)

    def prepare_save(self):
        self.discord_member = None

    def reload(self, guild: discord.Guild):
        self.discord_member = guild.get_member(self.discord_id)

    @staticmethod
    def name_to_partial_player(name: str):
        return Player(
                 name=name,
                 mmr=0,
                 lr=0,
                 time_queued=datetime.datetime.now(),
                 can_host=False,
                 drop_warned=False,
                 queue_channel_id=0,
                 discord_id=0,
                 last_active=datetime.datetime.now(),
                 discord_member=None)

    @staticmethod
    def discord_member_to_partial_player(member: discord.Member):
        return Player(
                 name=member.display_name,
                 mmr=0,
                 lr=0,
                 time_queued=datetime.datetime.now(),
                 can_host=False,
                 drop_warned=False,
                 queue_channel_id=0,
                 discord_id=member.id,
                 last_active=datetime.datetime.now(),
                 discord_member=member)

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


class Group(list):
    MAX_PLAYERS = 12

    def __init__(self, iterable):
        if len(iterable) > Group.MAX_PLAYERS:
            raise TooManyPlayers()
        super().__init__(iterable)

    def append(self, player: Player):
        if (len(self) + 1) > Group.MAX_PLAYERS:
            raise TooManyPlayers()
        super().append(player)

    def insert(self, index, item):
        if (len(self) + 1) > Group.MAX_PLAYERS:
            raise TooManyPlayers()
        super().insert(index, item)

    def add_singleton(self, group: 'Group'):
        if len(group) != 1:
            raise GroupCombination(f"Cannot add group with {len(group)} players to another group.")
        if (len(self) + 1) > Group.MAX_PLAYERS:
            raise TooManyPlayers()
        self.extend(group)
        group.clear()

    def extend(self, group: 'Group'):
        if not isinstance(group, Group):
            raise TypeError(f"Type Group cannot extend type given: {type(group)}")
        if (len(self) + len(group)) > Group.MAX_PLAYERS:
            raise TooManyPlayers()
        super().extend(group)

    def remove(self, player: Player):
        found_player = self.get(player)
        if found_player is not None:
            super().remove(found_player)
        return found_player

    def get(self, player: Player):
        if player in self:
            for p in self:
                if p.get_queue_key() == player.get_queue_key():
                    return p
        return None

    def __contains__(self, player: Player):
        return any(p.get_queue_key() == player.get_queue_key() for p in self)

    def prepare_save(self):
        for player in self:
            player.prepare_save()

    def reload(self, guild: discord.Guild):
        for player in self:
            player.reload(guild)
        self.remove_empty_players()

    def remove_empty_players(self):
        to_remove = []
        for i in range(len(self)):
            if self[i].discord_member is None:
                to_remove.append(i)
        for j in reversed(to_remove):
            self.pop(j)

    def can_add_player(self):
        return (len(self) + 1) <= Group.MAX_PLAYERS




class Queue(list):

    def add_to_queue(self, player: Player):
        self.append(Group([player]))

    def splinter_from_group(self, player: Player):
        for group in self:
            if player in group:
                self.append([group.remove(player)])  # Remove player from group and put in their own group
                break
        self.remove_empty_groups()

    def remove_from_queue(self, player: Player):
        removed = None
        for group in self:
            if player in group:
                removed = group.remove(player)
        self.remove_empty_groups()
        return removed

    def player_in_queue(self, player: Player) -> bool:
        """Returns if a given player is in the queue or not"""
        return any(lambda g: player in g, self)

    def remove_empty_groups(self):
        to_remove = []
        for i in range(len(self)):
            if len(self[i]) == 0:
                to_remove.append(i)
        for j in reversed(to_remove):
            self.pop(j)

    def prepare_save(self):
        for group in self:
            group.prepare_save()

    def reload(self, guild:discord.Guild):
        for group in self:
            group.reload(guild)
        self.remove_empty_groups()

    def __contains__(self, player: Player):
        return any(player in group for group in self)

    def get_player(self, player: Player):
        group = self.get_group(player)
        if group is not None:
            return group.get(player)

    def get_group(self, player: Player):
        for group in self:
            if player in group:
                return group

    def get_players(self) -> List[Player]:
        players = []
        for group in self:
            players.extend(group)
        return players

    def get_players_with_group_numbers(self) -> List[Tuple[int | None, Player]]:
        group_num = 1
        players = []
        for group in self:
            cur_group_num = None
            if len(group) > 1:
                cur_group_num = group_num
                group_num += 1
            for player in group:
                players.append((cur_group_num, player))
        players.sort(key=lambda t: t[1].time_queued)
        return players

    def count_players_queued(self):
        total = 0
        for group in self:
            total += len(group)
        return total


