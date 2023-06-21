import datetime
import typing


class TooManyFriends(Exception):
    pass


class Player:
    FRIEND_LIMIT = 2

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
        self._friends = []
        self._parent = None

    def update_active_time(self):
        self.last_active = datetime.datetime.now()

    def add_friend(self, friend: 'Player'):
        if len(self._friends) >= Player.FRIEND_LIMIT:
            raise TooManyFriends()
        self._friends.append(friend)

    def remove_friend(self, friend: 'Player'):
        self._friends = [p for p in self._friends if p.disord_id != friend.discord_id]

    def total_players(self):
        return 1 + len(self._friends)

    def get_friends(self):
        return self._friends

    def can_add_n_friends(self, number_to_add: int) -> bool:
        return len(self._friends) + number_to_add <= Player.FRIEND_LIMIT





