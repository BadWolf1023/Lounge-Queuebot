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

    def update_active_time(self):
        self.last_active = datetime.datetime.now()

    def add_friend(self, friend: 'Player'):
        if len(self._friends) >= Player.FRIEND_LIMIT:
            raise TooManyFriends()
        self._friends.append(friend)

    def remove_friend(self, friend: 'Player'):
        self._friends = [p for p in self._friends if p.disord_id != friend.discord_id]

    def get_low_mmr



