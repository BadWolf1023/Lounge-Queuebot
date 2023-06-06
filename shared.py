import datetime
import typing
import aiohttp

Player = typing.NamedTuple('Player',
                           name=str,
                           mmr=int,
                           lr=int,
                           time_queued=datetime.datetime,
                           drop_warned=bool,
                           queue_channel_id=int,
                           discord_id=int,
                           last_active=datetime.datetime)

MAX_LEN = 2000
RT_LADDER = "rt"
CT_LADDER = "ct"
WARN_DROP_TIME = 1000000000
AUTO_DROP_TIME = 10000000000
OWNERS = [1110408991839883274]


def split_large_str(to_split: str, max_len=MAX_LEN):
    split_strs = [""]
    for line in to_split.splitlines():
        if (len(line) + len(split_strs[-1])) > max_len:
            split_strs.append("")
        split_strs[-1] = split_strs[-1] + line + "\n"
    return split_strs


# noinspection PyBroadException
async def get_json_data(full_url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url) as r:
                if r.status == 200:
                    js = await r.json()
                    return js
    except Exception:
        return None
