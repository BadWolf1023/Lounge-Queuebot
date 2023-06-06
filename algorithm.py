from typing import List
from shared import Player
import datetime


MAX_MMR_RANGE = 7000
MAX_QUEUE_TIME = 60
LINEUP_SIZE = 12
SCORE_THRESHOLD = .1


def get_mmr_min_max(player_list):
    return min(player_list, key=lambda p: p.mmr).mmr, max(player_list, key=lambda p: p.mmr).mmr


def get_mmr_range(player_list):
    min_, max_ = get_mmr_min_max(player_list)
    return max_ - min_


def compute_mmr_range_score(mmr_range):
    # Formula for computing the score of the mmr range
    return (MAX_MMR_RANGE - mmr_range) / MAX_MMR_RANGE


def average(numbers):
    return sum(numbers) / len(numbers)


def get_minutes(dt: datetime.timedelta) -> int:
    return dt.seconds // 60


def compute_average_time_in_lineup(player_list: List[Player], time_reference=None):
    time_reference = datetime.datetime.now() if time_reference is None else time_reference
    return average([get_minutes(time_reference - x.time_queued) for x in player_list])


def compute_time_in_lineup_score(player_list: List[Player]):
    # Calculates the average of the player's queue times. Divides by MAX_QUEUE_TIME (to make a ratio)
    return compute_average_time_in_lineup(player_list) / MAX_QUEUE_TIME


def compute_lineup_score(player_list, breakdown=False):
    mmr_range = get_mmr_range(player_list)

    mmr_range_score = compute_mmr_range_score(mmr_range)
    lineup_queue_time_score = compute_time_in_lineup_score(player_list)

    if mmr_range > MAX_MMR_RANGE:
        mmr_range_score = 0

    total_score = 0
    if mmr_range_score != 0:
        total_score = mmr_range_score + lineup_queue_time_score

    if breakdown:
        return total_score, {"MMR Range": mmr_range,
                             "MMR Range Score": mmr_range_score,
                             "Average queue time": compute_average_time_in_lineup(player_list),
                             "Lineup Queue Time Score": lineup_queue_time_score}
    else:
        return total_score


def traverse_down(cur_list, all_list):
    if len(cur_list) == LINEUP_SIZE:
        return cur_list
    if len(all_list) == 0:
        return None

    best_addition_index = None
    best_addition_score = None
    for player_index, player in enumerate(all_list):
        lineup_score = compute_lineup_score(cur_list + [player])
        if best_addition_score is None or lineup_score > best_addition_score:
            best_addition_index = player_index
            best_addition_score = lineup_score

    # possible alpha beta pruning opportunity to stop if best addition score made lineup 0 or below acceptable threshold

    new_cur_list = cur_list + [all_list[best_addition_index]]
    new_all_player_list = all_list[0:best_addition_index] + all_list[best_addition_index + 1:]
    return traverse_down(new_cur_list, new_all_player_list)


def get_best_lineup_for_each_player(all_players):
    all_possibilities = set()
    if len(all_players) < LINEUP_SIZE:
        return all_possibilities

    for index, player in enumerate(all_players):
        temp_list = all_players[0:index] + all_players[index + 1:]
        result = traverse_down([player], temp_list)
        if result is not None:
            all_possibilities.add(frozenset(result))

    return all_possibilities
