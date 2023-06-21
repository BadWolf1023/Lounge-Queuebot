# Online Python - IDE, Editor, Compiler, Interpreter
import random

import player
import shared
import algorithm
import rating
import datetime
from typing import List
random.seed()


def get_lineup_debug_str(rt_queue_data, ct_queue_data):
    rt_player_data_str = get_player_data_str(rt_queue_data, ladder_type=shared.RT_LADDER)
    ct_player_data_str = get_player_data_str(ct_queue_data, ladder_type=shared.CT_LADDER)

    rt_best_lineups = algorithm.get_best_lineup_for_each_player(rt_queue_data)
    ct_best_lineups = algorithm.get_best_lineup_for_each_player(ct_queue_data)

    rt_best_lineup_str = get_best_lineups_str(rt_best_lineups, ladder_type=shared.RT_LADDER)
    ct_best_lineup_str = get_best_lineups_str(ct_best_lineups, ladder_type=shared.CT_LADDER)
    return rt_player_data_str, ct_player_data_str, rt_best_lineup_str, ct_best_lineup_str


def get_simulation_str(mllu_text: str):
    rt_player_list, ct_player_list = parse_mllu_text(mllu_text)
    rt_lounge_data = get_mmrs(rt_player_list, ladder_type=shared.RT_LADDER)
    ct_lounge_data = get_mmrs(ct_player_list, ladder_type=shared.CT_LADDER)
    return get_lineup_debug_str(rt_lounge_data, ct_lounge_data)


def parse_mllu_text(text: str):
    rt_player_list = set()
    ct_player_list = set()
    rt_flag = True
    for line in text.splitlines():
        players_to_add = []
        if "full mogi" in line or "active mogi" in line:
            pass
        elif "rt-tier" in line:
            rt_flag = True
            pass
        elif "ct-tier" in line:
            rt_flag = False
            pass
        elif "Last updated" in line or "This will update every" in line or line.strip() == "":
            pass
        elif line.startswith("Team"):
            players_text = line.split(":")[1].strip()
            players_to_add = players_text.split(", ")
        else:
            players_to_add = line.split(", ")

        if rt_flag:
            rt_player_list.update(players_to_add)
        else:
            ct_player_list.update(players_to_add)
    return list(rt_player_list), list(ct_player_list)


def get_mmrs(player_list, ladder_type: str):
    if len(player_list) == 0:
        return []

    new_player_list = []
    cur_time = datetime.datetime.now()
    for player_name in player_list:
        player_rating = rating.get_player_rating(player_name, ladder_type)
        if player_rating is None:
            print(f"Could not find a {ladder_type} rating for {player_name}")
        else:
            min_queued = random.randrange(0, algorithm.MAX_QUEUE_TIME, 1)
            new_player_list.append(player.Player(player_name,
                                                 player_rating[0],
                                                 player_rating[1],
                                                 cur_time - datetime.timedelta(minutes=min_queued),
                                                 False,
                                                 False,
                                                 0,
                                                 0,
                                                 cur_time)
                                   )

    return new_player_list


def get_best_lineups_str(best_lineups, ladder_type: str, header=True):
    text_str = ""
    if header:
        text_str = f"For each player, the best lineup for that player was computed. " \
                   f"Then, duplicate lineups were removed. {ladder_type.upper()} results:\n"
    if len(best_lineups) == 0:
        text_str += "None found\n"
    else:
        cur_time = datetime.datetime.now()
        for lineup in sorted(best_lineups, key=algorithm.compute_lineup_score):
            total_score, breakdown = algorithm.compute_lineup_score(lineup, breakdown=True)
            for descriptor in breakdown:
                if type(breakdown[descriptor]) == float:
                    breakdown[descriptor] = round(breakdown[descriptor], 3)
            total_score = round(total_score, 3)
            breakdown_str = '\n\t'.join([str(desc)+': '+str(val) for desc, val in breakdown.items()])
            lineup_str = "\n\t\t".join(get_player_str(p, cur_time) for p in sorted(lineup,
                                                                                   key=lambda z: z.mmr, reverse=True)
                                       )
            text_str += f"Score: {total_score}\n\t{breakdown_str}\n\t\t{lineup_str}\n"

    return text_str + "\n-------------------------------------------------------------------------------\n"


def get_player_str(player: player.Player, time_reference=None) -> str:
    time_reference = datetime.datetime.now() if time_reference is None else time_reference
    player_mmr_str = f"{player.mmr} MMR"
    return f"{player.name:<15} | {player_mmr_str:>9} | {algorithm.get_minutes(time_reference-player.time_queued):<3}" \
           f" minutes queued"


def get_player_data_str(players: List[player.Player], ladder_type: str):
    text_str = f"{ladder_type.upper()} Data:"
    cur_time = datetime.datetime.now()
    for player in sorted(players, key=lambda z: z.mmr, reverse=True):
        text_str += f"\n{get_player_str(player, cur_time)}"
    return text_str
