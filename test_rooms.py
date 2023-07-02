import unittest
from game_queue import Player

Room = None


class EvenRoomTest(unittest.TestCase):
    def setUp(self):
        self.players_1 = []
        mmrs = [0, 100, 50, 45]
        for i in range(4):
            self.players_1.append(
                Player(name=f"Player #{i}",
                       mmr=mmrs[i],
                       lr=mmrs[i],
                       time_queued=None,
                       can_host=False,
                       drop_warned=False,
                       queue_channel_id=0,
                       discord_id=0,
                       last_active=None,
                       discord_member=None)
            )

        self.room_1 = Room(self.players_1, "RT")

        self.players_2 = []
        mmrs = [0, 100, 50, 55, 40, 30, 20, 10, 10, 20, 30, 40]
        for i in range(12):
            self.players_2.append(
                Player(name=f"Player #{i}",
                       mmr=mmrs[i],
                       lr=mmrs[i],
                       time_queued=None,
                       can_host=False,
                       drop_warned=False,
                       queue_channel_id=0,
                       discord_id=0,
                       last_active=None,
                       discord_member=None)
            )

        self.room_2 = Room(self.players_2, "RT")

    def test_room_even_teams_1(self):
        team_1_result = {self.players_1[0], self.players_1[1]}
        team_2_result = {self.players_1[2], self.players_1[3]}
        self.room_1.make_even_teams(self.players_1, 2)
        team_1 = set(self.room_1.teams[0])
        team_2 = set(self.room_1.teams[1])

        team_1_correct = team_1 == team_1_result or team_1 == team_2_result
        self.assertTrue(team_1_correct, f"Team 1 is not correct for 4 players:\nCorrect team 1 and 2 result:\n{team_1_result}\n{team_2_result}\nActual team 1: {team_1}")
        team_2_correct = team_2 == team_1_result or team_2 == team_2_result
        self.assertTrue(team_2_correct, f"Team 2 is not correct for 4 players:\nCorrect team 1 and 2 result:\n{team_1_result}\n{team_2_result}\nActual team 2: {team_2}")

    def test_room_even_teams_2(self):
        self.room_1.make_even_teams(self.players_2, 2)
        team_1 = self.room_1.teams[0]
        team_2 = self.room_1.teams[1]
        team_1_mmr_sum = sum(p.mmr for p in team_1)
        team_2_mmr_sum = sum(p.mmr for p in team_2)
        self.assertTrue(abs(team_1_mmr_sum-team_2_mmr_sum) == 5, "Total difference between team mmrs should be 5.")



def set_room(r):
    global Room
    Room = r


if __name__ == '__main__':
    unittest.main()
