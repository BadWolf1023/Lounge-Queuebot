from typing import List
from game_queue import Player
import datetime


MAX_MMR_RANGE = 6000
MAX_QUEUE_TIME = 60
LINEUP_SIZE = 12
SCORE_THRESHOLD = 1.2

MAX_MMR = 12000
MIN_MMR = -1000
def get_mmr(player: Player):
    if player.mmr > MAX_MMR:
        return MAX_MMR
    elif player.mmr < MIN_MMR:
        return MIN_MMR
    else:
        return player.mmr


def get_mmr_min_max(player_list):
    return get_mmr(min(player_list, key=get_mmr)), get_mmr(max(player_list, key=get_mmr))


def get_mmr_range(player_list):
    min_, max_ = get_mmr_min_max(player_list)
    return max_ - min_


def compute_mmr_range_score(mmr_range):
    # Formula for computing the score of the mmr range
    return (MAX_MMR_RANGE - mmr_range) / MAX_MMR_RANGE


def average(numbers):
    return sum(numbers) / len(numbers)

def average_mmr(player_list):
    return average([get_mmr(p) for p in player_list])

def compute_avg_mmr_bonus_score(player_list):
    avg_mmr = average_mmr(player_list)
    SCALE_FACTOR = .3
    return ((avg_mmr - 5000) ** 2) / (10**8) * SCALE_FACTOR


def get_minutes(dt: datetime.timedelta) -> int:
    return dt.seconds // 60


def compute_average_time_in_lineup(player_list: List[Player], time_reference=None):
    time_reference = datetime.datetime.now() if time_reference is None else time_reference
    return average([get_minutes(time_reference - x.time_queued) for x in player_list])


def compute_time_in_lineup_score_VALENCE(player_list: List[Player]):
    # Calculates the score of a lineup's average queue time according to the following formula:
    # https://www.desmos.com/calculator/p3anl9d2yr
    avg_queue_time = compute_average_time_in_lineup(player_list)
    eq_exp = -1 * (2 * avg_queue_time - 30)
    return 1 / (1 + 1.05**eq_exp)

def compute_time_in_lineup_score(player_list: List[Player]):
    # Calculates the score of a lineup's average queue time according to a certain formula
    return compute_time_in_lineup_score_VALENCE(player_list)


def compute_lineup_score(player_list, breakdown=False):
    mmr_range = get_mmr_range(player_list)

    mmr_range_score = compute_mmr_range_score(mmr_range)
    lineup_queue_time_score = compute_time_in_lineup_score(player_list)
    avg_mmr_bonus_score = compute_avg_mmr_bonus_score(player_list)

    if mmr_range > MAX_MMR_RANGE:
        mmr_range_score = 0

    total_score = 0
    if mmr_range_score != 0:
        total_score = mmr_range_score + lineup_queue_time_score

    if breakdown:
        return total_score, {"MMR Range": mmr_range,
                             "MMR Range Score": mmr_range_score,
                             "Average queue time": compute_average_time_in_lineup(player_list),
                             "Lineup Queue Time Score": lineup_queue_time_score,
                             "Average MMR": average_mmr(player_list),
                             "Average MMR bonus score": avg_mmr_bonus_score}
    else:
        return total_score


def traverse_down(cur_list, all_list):
    if len(cur_list) == LINEUP_SIZE:
        return cur_list

    best_addition_index = None
    best_addition_score = None
    for group_index, group in enumerate(all_list):
        if (len(cur_list) + len(group)) > LINEUP_SIZE:
            continue
        lineup_score = compute_lineup_score(cur_list + group)
        if best_addition_score is None or lineup_score > best_addition_score:
            best_addition_index = group_index
            best_addition_score = lineup_score

    # possible alpha beta pruning opportunity to stop if best addition score made lineup 0 or below acceptable threshold

    if best_addition_index is None:
        return None

    new_cur_list = cur_list + all_list[best_addition_index]
    new_all_player_list = all_list[0:best_addition_index] + all_list[best_addition_index + 1:]
    return traverse_down(new_cur_list, new_all_player_list)


def get_best_lineup_for_each_group(queue):
    all_possibilities = set()
    if queue.count_players_queued() < LINEUP_SIZE:
        return all_possibilities

    for index, group in enumerate(queue):
        temp_list = queue[0:index] + queue[index + 1:]
        result = traverse_down([p for p in group], temp_list)
        if result is not None:
            all_possibilities.add(frozenset(result))

    return all_possibilities
