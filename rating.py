import shared
import datetime
import pickle
import logging

RT_MMR_DATA = {}
CT_MMR_DATA = {}
last_pull_time_rt = None
last_pull_time_ct = None
minimum_time_before_pull = datetime.timedelta(minutes=15)

PLAYER_NAME_FIELD_NAME = "player_name"
PLAYER_ID_FIELD_NAME = "player_id"
PLAYER_DISCORD_ID_FIELD_NAME = "player_id"
PLAYER_MMR_FIELD_NAME = "current_mmr"
PLAYER_LR_FIELD_NAME = "current_lr"


async def pull_mmr_data(ladder_type: str):
    global last_pull_time_rt, last_pull_time_ct
    mmr_api_link = f"https://mkwlounge.gg/api/ladderplayer.php?ladder_type={ladder_type}&all&fields=" \
                   f"{PLAYER_NAME_FIELD_NAME},{PLAYER_ID_FIELD_NAME},{PLAYER_MMR_FIELD_NAME}," \
                   f"{PLAYER_LR_FIELD_NAME},{PLAYER_DISCORD_ID_FIELD_NAME}"
    cur_time = datetime.datetime.now()
    last_pull_time = last_pull_time_rt if ladder_type == shared.RT_LADDER else last_pull_time_ct
    if last_pull_time is not None and cur_time < (last_pull_time + minimum_time_before_pull):
        return

    response = await shared.get_json_data(mmr_api_link)
    if response is None:
        return
    if ladder_type == shared.RT_LADDER:
        mmr_data = RT_MMR_DATA
        last_pull_time_rt = cur_time
    else:
        mmr_data = CT_MMR_DATA
        last_pull_time_ct = cur_time

    mmr_data.clear()
    for player in response['results']:
        mmr_data[player[PLAYER_NAME_FIELD_NAME].lower()] = (player[PLAYER_NAME_FIELD_NAME],
                                                            player[PLAYER_DISCORD_ID_FIELD_NAME],
                                                            player[PLAYER_MMR_FIELD_NAME],
                                                            player[PLAYER_LR_FIELD_NAME])


def get_player_rating(player: str | int, ladder_type: str):
    mmr_data = RT_MMR_DATA if ladder_type == shared.RT_LADDER else CT_MMR_DATA
    lookup = player
    if isinstance(player, str):
        lookup = player.lower()
        mmr_data.get(lookup)
    elif isinstance(player, int):
        for data in mmr_data.values():
            if data[1] == player:
                return data


def save_data():
    to_dump = {"RT_MMR_DATA": RT_MMR_DATA,
               "CT_MMR_DATA": CT_MMR_DATA,
               "last_pull_time_rt": last_pull_time_rt,
               "last_pull_time_ct": last_pull_time_ct}
    with open("rating_pkl", "wb") as f:
        pickle.dump(to_dump, f)


def load_data():
    try:
        with open("rating_pkl", "rb") as f:
            to_load = pickle.load(f)
            RT_MMR_DATA.clear()
            RT_MMR_DATA.update(to_load["RT_MMR_DATA"])
            CT_MMR_DATA.clear()
            CT_MMR_DATA.update(to_load["CT_MMR_DATA"])
            global last_pull_time_rt, last_pull_time_ct
            last_pull_time_rt = to_load["last_pull_time_rt"]
            last_pull_time_ct = to_load["last_pull_time_ct"]
    except Exception as e:
        logging.critical("Failed to load rating pickle:")
        logging.critical(e)
